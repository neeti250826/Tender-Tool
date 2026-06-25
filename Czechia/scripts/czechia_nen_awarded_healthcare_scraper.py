#!/usr/bin/env python3
"""
Scrape awarded Czech NEN public procurements related to medical / healthcare.

Designed for the no-JavaScript public NEN pages at https://nen.nipez.cz.
Default output is ONE Excel workbook with ONE sheet:
  - czechia_nen_awarded_healthcare_item_details_only.xlsx
  - sheet: Item_Details
  - one row per tender x awarded contract x subject item combination
  - tender, buyer, classification, awarded supplier/date, contract price, publication,
    translation, and item-detail fields are all flattened into the same row.

The script also writes debug/log files so you can see progress and diagnose errors:
  - scrape_debug.log
  - scrape_log.jsonl
  - summary.json
  - translation_cache.json
  - queries_used.txt

Optional outputs:
  - --write-csv writes all_columns.csv
  - --write-detail-sheets writes the old multi-sheet workbook for auditing only

Typical run:
  python czechia_nen_awarded_healthcare_scraper_SINGLE_EXCEL_v3.py --start-date 2024-01-01 --output-dir ./nen_awarded_healthcare_2024_recent --debug

Notes:
  - NEN's list pages are paginated and the exact page markup can change. The parser uses
    both HTML table parsing and text fallbacks.
  - Translation uses Google's public translate endpoint by default. Use --translate none
    if translation is too slow or blocked.
  - Status filter is strict: the detail page field "CURRENT STATUS OF THE PROCUREMENT PROCEDURE" must be Awarded (English) or Zadán (Czech).
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import logging
import os
import random
import re
import sys
import time
import unicodedata
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable, Optional
from urllib.parse import quote, urljoin, urlparse

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

try:
    import requests
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Missing dependency: requests. Install with: pip install requests") from exc

try:
    from bs4 import BeautifulSoup, NavigableString, Tag
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Missing dependency: beautifulsoup4. Install with: pip install beautifulsoup4") from exc

try:
    import pandas as pd
except ImportError:
    pd = None

BASE_URL = "https://nen.nipez.cz"
LIST_PATH_CZ = "/verejne-zakazky"
NEN_ID_URL_RE = re.compile(r"N006-\d{2}-V\d{8}", re.I)
NEN_ID_DISPLAY_RE = re.compile(r"N006[/\-]\d{2}[/\-]V\d{8}", re.I)
DATE_RE = re.compile(r"(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})(?:\s+(\d{1,2}):(\d{2}))?")
DATE_RE_ALT = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4}),?\s*(\d{1,2}):(\d{2})\s*([AP]M)?", re.I)
MULTISPACE_RE = re.compile(r"\s+")

# Strict awarded-only statuses from the tender DETAIL page field:
#   English: CURRENT STATUS OF THE PROCUREMENT PROCEDURE = Awarded
#   Czech:   Aktuální stav ZP = Zadán
# Do NOT include "Termination of performance" / "Ukončení plnění" by default, because
# those are not the same as the current status "Awarded" requested by the user.
AWARDED_STATUSES = {
    "zadan",
    "zadán",
    "awarded",
}

MEDICAL_CPV_PREFIXES = (
    "33",  # Medical equipment, pharmaceuticals and personal care products
    "85",  # Health and social work services
)

MEDICAL_KEYWORDS = [
    "zdravot", "zdravotni", "zdravotnick", "zdravotnictvi", "nemocnic", "klinick", "pacient",
    "leciv", "lečiv", "leky", "léky", "lekarn", "lékarn", "farmaceut", "pharma", "medicine",
    "diagnost", "laborator", "laboratoř", "laboratory", "analyz", "analyzator", "analyzátor",
    "stomatolog", "dental", "chirurg", "surgical", "implant", "ortoped", "rehabilit",
    "vakcin", "vaccine", "veterinar", "veterinár", "ambulanc", "ordinac", "hospital",
    "medical", "healthcare", "health care", "pharmaceutical", "clinic", "clinical",
    "rousk", "rouš", "obvaz", "bandage", "katetr", "catheter", "steril", "hygien",
    "laboratorni", "laboratorní", "idexx", "procyte", "catalyst", "spotrebni zdravot", "spotřební zdravot",
]

MEDICAL_ITEM_KEYWORDS = [
    "zdravotnicky material", "zdravotnicke prostredky", "zdravotnicke pristroje",
    "zdravotnicky spotrebni", "lekarske pristroje", "lekarsky nabytek",
    "leciva", "lecive pripravky", "farmaceut", "pharma", "diagnost",
    "laborator", "laboratorni", "analyzator", "reagencie", "reagens",
    "testovaci soupr", "implant", "katetr", "steril", "dezinfek",
    "infuz", "infuze", "jehla", "jehly", "strikack", "obvaz",
    "bandaz", "chirurg", "endoskop", "ultrazvuk", "rentgen", "anestez",
    "fyzioterap", "rehabilitac", "masaz", "masazni", "nemocnicni",
    "ordinac", "ambulanc", "lekarsk", "sestra", "zachranar", "defibrilator",
    "ekg", "oxymetr", "tonometr", "glukometr", "odsavack", "kanyla",
    "sonda", "monitor pacient", "luzko", "luzka", "vozík", "vozik",
]

DEFAULT_QUERIES = [
    # Broad Czech stems/terms. NEN quick search is not guaranteed to be diacritic-insensitive,
    # so both accented and unaccented forms are included where useful.
    "zdravotnick",
    "zdravotní",
    "zdravotni",
    "zdravotnictví",
    "nemocnice",
    "pacient",
    "léčiv",
    "leciv",
    "léky",
    "farmaceut",
    "diagnost",
    "laborator",
    "analyzátor",
    "analyzator",
    "stomatolog",
    "chirurg",
    "implant",
    "rehabilitace",
    "veterinární",
    "veterinarni",
    "ambulance",
    "ordinace",
    "obvaz",
    "katetr",
    "steril",
    # English terms sometimes occur in NEN records.
    "medical",
    "healthcare",
    "hospital",
    "pharmaceutical",
    "diagnostic",
    "zdravotnicke prostredky",
    "zdravotnicky material",
    "spotrebni material",
    "lecive pripravky",
    "diagnostika",
    "laboratorni",
    "reagencie",
    "implantaty",
    "dezinfekce",
    "ultrazvuk",
    "rentgen",
    "endoskop",
    "infuzni",
    "strikacky",
]

TRANSLATE_COLUMNS_TENDER = [
    "tender_name_cs",
    "contracting_authority_cs",
    "status_cs",
    "public_contract_regime_cs",
    "procurement_procedure_type_cs",
    "procurement_procedure_specification_cs",
    "type_cs",
    "currency_cs",
    "subject_description_cs",
    "nipez_name_cs",
    "main_place_of_performance_cs",
    "cpv_name_cs",
    "subject_matter_name_cs",
    "place_performance_text_cs",
]

TRANSLATE_COLUMNS_ITEM = [
    "item_name_cs",
    "item_cpv_name_cs",
    "item_description_cs",
    "item_uom_cs",
]

TRANSLATE_COLUMNS_PUBLICATION = ["publication_cs"]
TRANSLATE_COLUMNS_DOCUMENT = ["document_type_cs"]


FIELD_ALIASES = {
    # Basic information
    "nazev zadavaciho postupu": "tender_name_cs",
    "procurement procedure name": "tender_name_cs",
    "zadavatel": "contracting_authority_cs",
    "contracting authority": "contracting_authority_cs",
    "systemove cislo nen": "nen_system_number",
    "nen system number": "nen_system_number",
    "aktualni stav zp": "status_cs",
    "current status of the procurement procedure": "status_cs",
    "rozdeleni na casti": "division_into_lots_cs",
    "division into lots": "division_into_lots_cs",
    "evidencni cislo zakazky ve vvz": "vvz_registration_number",
    "contract registration number in the vvz": "vvz_registration_number",
    "identifikator zp na profilu zadavatele": "contracting_authority_profile_procedure_id",
    "procurement procedure id on the contracting authority's profile": "contracting_authority_profile_procedure_id",
    "identifikator nipez": "nipez_identifier",
    "identifier of nipez": "nipez_identifier",
    "rezim vz dle volby zadavatele": "public_contract_regime_cs",
    "public contract regime": "public_contract_regime_cs",
    "druh zadavaciho postupu": "procurement_procedure_type_cs",
    "procurement procedure type": "procurement_procedure_type_cs",
    "specifikace zadavaciho rizeni": "procurement_procedure_specification_cs",
    "specifications of the procurement procedure": "procurement_procedure_specification_cs",
    "druh": "type_cs",
    "type": "type_cs",
    "predpokladana hodnota bez dph": "estimated_value_excl_vat",
    "estimated value excl vat": "estimated_value_excl_vat",
    "mena": "currency_cs",
    "currency": "currency_cs",
    "datum zruseni zp": "cancellation_date",
    "date of cancellation of pp": "cancellation_date",
    "datum uverejneni zp na profil": "publication_date",
    "date of publication on profile": "publication_date",
    # Submission
    "lhuta pro podani nabidek": "submission_deadline",
    "deadline for submitting tenders": "submission_deadline",
    # Contact
    "titul pred jmenem": "contact_title_before_name",
    "title before name": "contact_title_before_name",
    "jmeno": "contact_first_name",
    "name": "contact_first_name",
    "prijmeni": "contact_surname",
    "surname": "contact_surname",
    "e-mail": "contact_email",
    "email": "contact_email",
    "telefon 1": "contact_phone_1",
    "phone 1": "contact_phone_1",
    "telefon 2": "contact_phone_2",
    "phone 2": "contact_phone_2",
    # Subject matter
    "popis predmetu": "subject_description_cs",
    "subject-matter description": "subject_description_cs",
    "kod z ciselniku nipez": "nipez_code",
    "code from the nipez code list": "nipez_code",
    "nazev z ciselniku nipez": "nipez_name_cs",
    "name from the nipez code list": "nipez_name_cs",
    "hlavni misto plneni": "main_place_of_performance_cs",
    "main place of performance": "main_place_of_performance_cs",
    "kod z ciselniku cpv": "cpv_code",
    "code from the cpv code list": "cpv_code",
    "nazev z ciselniku cpv": "cpv_name_cs",
    "name from the cpv code list": "cpv_name_cs",
    "nazev predmetu": "subject_matter_name_cs",
    "subject-matter name": "subject_matter_name_cs",
    "textove pole pro popis mista plneni": "place_performance_text_cs",
    "text field for description of place of performance": "place_performance_text_cs",
    # Additional info
    "vz zadavana na zaklade rs/rd": "awarded_on_basis_framework_agreement_cs",
    "awarded on the basis of a framework agreement": "awarded_on_basis_framework_agreement_cs",
    "ramcova smlouva/dohoda": "framework_agreement_reference",
    "framework contract/agreement": "framework_agreement_reference",
    "zadavane v dns": "awarded_in_dns_cs",
    "awarded in a dns": "awarded_in_dns_cs",
    "vysledkem zp bude zavedeni dns": "result_will_be_dns_cs",
    "the result of the pp will be the implementation of a dns": "result_will_be_dns_cs",
    "jedna se o ramcovou dohodu": "is_framework_agreement_cs",
    "this is a framework agreement": "is_framework_agreement_cs",
    "importovana vz": "imported_public_contract_cs",
    "imported public contract": "imported_public_contract_cs",
}

ITEM_FIELD_ALIASES = {
    "nazev polozky": "item_name_cs",
    "item name": "item_name_cs",
    "kod z cpv": "item_cpv_code",
    "cpv code": "item_cpv_code",
    "nazev z cpv": "item_cpv_name_cs",
    "cpv name": "item_cpv_name_cs",
    "popis polozky": "item_description_cs",
    "item description": "item_description_cs",
}

# Extra item detail aliases. NEN item detail pages can expose quantity/unit fields with
# slightly different Czech or English labels depending on language and procedure type.
ITEM_FIELD_ALIASES.update({
    "merna jednotka": "item_uom_cs",
    "měrná jednotka": "item_uom_cs",
    "unit of measure": "item_uom_cs",
    "unit": "item_uom_cs",
    "jednotka": "item_uom_cs",
    "mnozstvi": "item_quantity",
    "množství": "item_quantity",
    "quantity": "item_quantity",
    "predpokladane mnozstvi": "item_quantity",
    "předpokládané množství": "item_quantity",
    "estimated quantity": "item_quantity",
    "celkove mnozstvi": "item_quantity",
    "celkové množství": "item_quantity",
    "total quantity": "item_quantity",
    "hodnota polozky": "item_estimated_value",
    "hodnota položky": "item_estimated_value",
    "item value": "item_estimated_value",
    "predpokladana hodnota polozky": "item_estimated_value",
    "předpokládaná hodnota položky": "item_estimated_value",
    "estimated item value": "item_estimated_value",
})

SECTION_NAMES = {
    "publication_records": [
        "evidence uverejneni v nen",
        "publication records in the nen system",
        "evidence uveřejnění v nen",
    ],
    "place_performance": ["misto plneni", "place of performance", "místo plnění"],
    "subject_items": ["polozky predmetu", "subject-matter items", "položky předmětu"],
    "vvz_publication_records": ["evidence uverejneni ve vvz", "publication records in the vvz", "evidence uveřejnění ve vvz"],
    "contracts": ["dodavatele, s nimiz byla smlouva uzavrena", "economic operators with whom a contract has been concluded"],
    "documents": ["uverejnene dokumenty", "published documents", "uveřejněné dokumenty"],
    "participants": ["seznam ucastniku", "list of participants", "seznam účastníků"],
}


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("\xa0", " ").replace("\u200b", " ")
    text = text.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    text = MULTISPACE_RE.sub(" ", text).strip()
    return text


def strip_accents(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))


def norm_key(text: str) -> str:
    text = clean_text(text).lower()
    text = strip_accents(text)
    text = re.sub(r"[^a-z0-9]+", " ", text, flags=re.I)
    return clean_text(text)


def safe_col(text: str, prefix: str = "field") -> str:
    key = norm_key(text).replace(" ", "_")
    if not key:
        key = hashlib.md5(text.encode("utf-8", "ignore")).hexdigest()[:10]
    return f"{prefix}_{key[:90]}"


def display_id_to_url_id(nen_id: str) -> str:
    return clean_text(nen_id).replace("/", "-")


def url_id_to_display_id(url_id: str) -> str:
    parts = url_id.split("-")
    if len(parts) == 3:
        return f"{parts[0]}/{parts[1]}/{parts[2]}"
    return url_id.replace("-", "/")


def parse_datetime(value: str) -> tuple[str, str]:
    """Return (iso_datetime, iso_date) where possible."""
    value = clean_text(value)
    if not value:
        return "", ""
    m = DATE_RE.search(value)
    if m:
        day, month, year, hour, minute = m.groups()
        h = int(hour) if hour else 0
        mi = int(minute) if minute else 0
        try:
            d = dt.datetime(int(year), int(month), int(day), h, mi)
            return d.isoformat(timespec="minutes"), d.date().isoformat()
        except ValueError:
            return "", ""
    m = DATE_RE_ALT.search(value)
    if m:
        # NEN English pages use mm/dd/yyyy in search snippets; be conservative and parse as month/day.
        month, day, year, hour, minute, ampm = m.groups()
        h = int(hour)
        if ampm:
            if ampm.upper() == "PM" and h < 12:
                h += 12
            if ampm.upper() == "AM" and h == 12:
                h = 0
        try:
            d = dt.datetime(int(year), int(month), int(day), h, int(minute))
            return d.isoformat(timespec="minutes"), d.date().isoformat()
        except ValueError:
            return "", ""
    return "", ""


def parse_decimal(value: str) -> str:
    value = clean_text(value)
    if not value:
        return ""
    # Keep only a number-like substring. Czech decimals use comma.
    m = re.search(r"[-+]?\d[\d\s.\u00a0]*,?\d*", value)
    if not m:
        return ""
    num = m.group(0).replace(" ", "").replace("\xa0", "")
    # Ambiguous: periods may be thousands separators in English output. Strip them if comma is present.
    if "," in num:
        num = num.replace(".", "").replace(",", ".")
    else:
        # If several dot groups, probably thousand separators.
        if num.count(".") > 1:
            num = num.replace(".", "")
    return num


def as_boolish(value: str) -> str:
    v = norm_key(value)
    if v in {"ano", "yes", "true"}:
        return "yes"
    if v in {"ne", "no", "false"}:
        return "no"
    return clean_text(value)


def contains_medical_text(*values: str) -> bool:
    hay = " ".join(clean_text(v) for v in values if v)
    hay_norm = strip_accents(hay.lower())
    return any(strip_accents(k.lower()) in hay_norm for k in MEDICAL_KEYWORDS)


def contains_medical_item_text(*values: str) -> bool:
    hay = " ".join(clean_text(v) for v in values if v)
    hay_norm = strip_accents(hay.lower())
    return any(strip_accents(k.lower()) in hay_norm for k in MEDICAL_ITEM_KEYWORDS)


def has_medical_cpv_prefix(code: str) -> bool:
    code = clean_text(code)
    return bool(code and code[:2] in MEDICAL_CPV_PREFIXES)


def is_medical_record(row: dict[str, Any]) -> bool:
    cpv = clean_text(row.get("cpv_code", ""))
    if has_medical_cpv_prefix(cpv):
        return True
    return contains_medical_text(
        row.get("tender_name_cs", ""),
        row.get("subject_description_cs", ""),
        row.get("cpv_name_cs", ""),
        row.get("nipez_name_cs", ""),
        row.get("subject_matter_name_cs", ""),
    )


def is_medical_item_row(tender: dict[str, Any], item: dict[str, Any]) -> bool:
    if has_medical_cpv_prefix(item.get("item_cpv_code", "")):
        return True
    item_has_medical_text = contains_medical_item_text(
        item.get("item_name_cs", ""),
        item.get("item_description_cs", ""),
        item.get("item_cpv_name_cs", ""),
    )
    if item_has_medical_text:
        return True
    if item.get("item_source") == "tender_document_spreadsheet":
        return False
    if has_medical_cpv_prefix(tender.get("cpv_code", "")):
        return True
    return contains_medical_item_text(
        tender.get("tender_name_cs", ""),
        tender.get("subject_description_cs", ""),
        tender.get("cpv_name_cs", ""),
        tender.get("nipez_name_cs", ""),
        tender.get("subject_matter_name_cs", ""),
    )


def is_awarded_status(status: str) -> bool:
    """Return True only when the tender detail page current status is Awarded/Zadán.

    This intentionally checks the parsed DETAIL PAGE field mapped from
    "CURRENT STATUS OF THE PROCUREMENT PROCEDURE" / "Aktuální stav ZP".
    It does not treat "Termination of performance" as awarded.
    """
    ns = norm_key(status)
    return ns in {norm_key(s) for s in AWARDED_STATUSES}


def build_search_url(query: str, page: int) -> str:
    """Build the NEN advanced-search URL.

    Important: this uses the same advanced-search filter shown on the website:
        Current status = Awarded / Zadán

    In NEN's encoded route state this is represented as:
        stavZP=zadana

    We keep the medical/healthcare keyword exactly as the search query and add
    the Awarded filter at the list-search level, so the list page itself should
    return awarded tenders only. The publication-date range is still verified
    from each tender detail page because NEN's no-JavaScript public route exposes
    the status filter reliably, while the date-picker route parameter names are
    not stable across language/UI builds.
    """
    query = clean_text(query)
    state_parts = ["stavZP=zadana"]
    if query:
        state_parts.append(f"query={query}")
    state_parts.append(f"page={page}")
    segment = quote("p:vz:" + "&".join(state_parts), safe="")
    return f"{BASE_URL}{LIST_PATH_CZ}/{segment}"


def canonical_detail_url(nen_url_id: str) -> str:
    return f"{BASE_URL}{LIST_PATH_CZ}/detail-zakazky/{display_id_to_url_id(nen_url_id)}"


def canonical_result_url(nen_url_id: str) -> str:
    return canonical_detail_url(nen_url_id).rstrip("/") + "/vysledek"


@dataclass
class Fetcher:
    timeout: int = 40
    retries: int = 7
    delay: float = 0.45
    cache_dir: Optional[Path] = None
    session: requests.Session = field(default_factory=requests.Session)

    def __post_init__(self) -> None:
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (compatible; Clearstate-NEN-healthcare-scraper/1.0; +https://nen.nipez.cz)",
                "Accept-Language": "cs,en;q=0.8",
            }
        )
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{digest}.html"  # type: ignore[operator]

    def _binary_cache_path(self, url: str, suffix: str = ".bin") -> Path:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{digest}{suffix}"  # type: ignore[operator]

    @staticmethod
    def _retry_after_seconds(response: requests.Response | None) -> float:
        if response is None:
            return 0.0
        value = clean_text(response.headers.get("Retry-After", ""))
        if not value:
            return 0.0
        if value.isdigit():
            return float(value)
        try:
            retry_at = dt.datetime.strptime(value, "%a, %d %b %Y %H:%M:%S GMT").replace(tzinfo=dt.timezone.utc)
            return max(0.0, (retry_at - dt.datetime.now(dt.timezone.utc)).total_seconds())
        except ValueError:
            return 0.0

    def _backoff_seconds(self, attempt: int, response: requests.Response | None = None, binary: bool = False) -> float:
        server_wait = self._retry_after_seconds(response)
        exponential = min(2 ** attempt, 90 if binary else 45)
        if response is not None and response.status_code == 429:
            exponential = min(exponential * (2.0 if binary else 1.5), 180 if binary else 90)
        return max(server_wait, exponential) + self.delay + random.uniform(0.5, 2.5)

    def get(self, url: str) -> str:
        if self.cache_dir:
            path = self._cache_path(url)
            if path.exists():
                logging.debug("CACHE HIT url=%s", url)
                return path.read_text(encoding="utf-8", errors="replace")
        last_error: Optional[Exception] = None
        for attempt in range(1, self.retries + 1):
            try:
                logging.debug("FETCH attempt=%s/%s url=%s", attempt, self.retries, url)
                response = self.session.get(url, timeout=self.timeout)
                if response.status_code in {429, 500, 502, 503, 504}:
                    raise requests.HTTPError(f"HTTP {response.status_code} for {url}", response=response)
                response.raise_for_status()
                response.encoding = response.encoding or "utf-8"
                text = response.text
                logging.debug("FETCH OK status=%s bytes=%s url=%s", response.status_code, len(text), url)
                if self.cache_dir:
                    self._cache_path(url).write_text(text, encoding="utf-8")
                    logging.debug("CACHE WRITE: %s", self._cache_path(url))
                time.sleep(self.delay + random.random() * 0.15)
                return text
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                response = exc.response if isinstance(exc, requests.HTTPError) else None
                wait = self._backoff_seconds(attempt, response=response, binary=False)
                logging.warning("Fetch failed attempt %s/%s: %s; retrying in %.1fs", attempt, self.retries, exc, wait)
                time.sleep(wait)
        raise RuntimeError(f"Failed to fetch {url}: {last_error}")

    def get_bytes(self, url: str, suffix: str = ".bin") -> bytes:
        if self.cache_dir:
            path = self._binary_cache_path(url, suffix=suffix)
            if path.exists():
                logging.debug("BINARY CACHE HIT url=%s", url)
                return path.read_bytes()
        last_error: Optional[Exception] = None
        for attempt in range(1, self.retries + 1):
            try:
                logging.debug("BINARY FETCH attempt=%s/%s url=%s", attempt, self.retries, url)
                response = self.session.get(url, timeout=self.timeout)
                if response.status_code in {429, 500, 502, 503, 504}:
                    raise requests.HTTPError(f"HTTP {response.status_code} for {url}", response=response)
                response.raise_for_status()
                data = response.content
                if self.cache_dir:
                    self._binary_cache_path(url, suffix=suffix).write_bytes(data)
                time.sleep(self.delay + random.random() * 0.15)
                return data
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                response = exc.response if isinstance(exc, requests.HTTPError) else None
                wait = self._backoff_seconds(attempt, response=response, binary=True)
                logging.warning("Binary fetch failed attempt %s/%s: %s; retrying in %.1fs", attempt, self.retries, exc, wait)
                time.sleep(wait)
        raise RuntimeError(f"Failed to fetch binary {url}: {last_error}")


class Translator:
    def __init__(self, mode: str, cache_path: Path, delay: float = 0.15) -> None:
        self.mode = mode.lower().strip()
        self.cache_path = cache_path
        self.delay = delay
        self.cache: dict[str, str] = {}
        if cache_path.exists():
            try:
                self.cache = json.loads(cache_path.read_text(encoding="utf-8"))
            except Exception:
                self.cache = {}
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0 Clearstate-NEN-Translator/1.0"})

    @staticmethod
    def _skip(text: str) -> bool:
        text = clean_text(text)
        if not text or len(text) <= 1:
            return True
        if re.fullmatch(r"[\d\s.,:/+\-()%]+", text):
            return True
        return False

    def translate(self, text: str, source: str = "cs", target: str = "en") -> str:
        text = clean_text(text)
        if self.mode == "none":
            return ""
        if self._skip(text):
            return text
        key = f"{source}|{target}|{text}"
        if key in self.cache:
            return self.cache[key]
        translated = ""
        if self.mode in {"google", "google-public", "public"}:
            translated = self._translate_google_public(text, source=source, target=target)
        elif self.mode == "same":
            translated = text
        else:
            logging.warning("Unknown translation mode %r; translation skipped", self.mode)
        if not translated:
            logging.warning("Translation unavailable; using source text as fallback for %r", text[:120])
            translated = text
        self.cache[key] = translated
        if len(self.cache) % 25 == 0:
            self.save()
        if translated:
            time.sleep(self.delay)
        return translated

    def _translate_google_public(self, text: str, source: str, target: str) -> str:
        # Split very long fields to reduce request failures.
        chunks = split_text_for_translation(text, max_chars=4200)
        out: list[str] = []
        for chunk in chunks:
            try:
                r = self.session.get(
                    "https://translate.googleapis.com/translate_a/single",
                    params={"client": "gtx", "sl": source, "tl": target, "dt": "t", "q": chunk},
                    timeout=25,
                )
                r.raise_for_status()
                data = r.json()
                translated = "".join(part[0] for part in data[0] if part and part[0])
                out.append(clean_text(translated))
            except Exception as exc:  # noqa: BLE001
                logging.warning("Translation failed: %s", exc)
                out.append("")
        return clean_text(" ".join(x for x in out if x))

    def save(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(self.cache, ensure_ascii=False, indent=2), encoding="utf-8")


def split_text_for_translation(text: str, max_chars: int = 4200) -> list[str]:
    text = clean_text(text)
    if len(text) <= max_chars:
        return [text]
    parts: list[str] = []
    current: list[str] = []
    current_len = 0
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if current_len + len(sentence) + 1 > max_chars and current:
            parts.append(" ".join(current))
            current = [sentence]
            current_len = len(sentence)
        else:
            current.append(sentence)
            current_len += len(sentence) + 1
    if current:
        parts.append(" ".join(current))
    return parts


def soup_from_html(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def get_visible_lines(soup: BeautifulSoup | Tag) -> list[str]:
    for bad in soup(["script", "style", "noscript"]):
        bad.decompose()
    lines = [clean_text(x) for x in soup.get_text("\n").split("\n")]
    return [x for x in lines if x]


def extract_h_fields(soup: BeautifulSoup | Tag, aliases: dict[str, str] | None = None) -> dict[str, str]:
    aliases = aliases or FIELD_ALIASES
    fields: dict[str, str] = {}
    for h in soup.find_all(re.compile(r"^h[1-6]$")):
        if not isinstance(h, Tag):
            continue
        if h.name not in {"h3", "h4"}:
            continue
        heading = clean_text(h.get_text(" ", strip=True))
        if not heading:
            continue
        values: list[str] = []
        for sib in h.next_siblings:
            if isinstance(sib, NavigableString):
                text = clean_text(str(sib))
                if text:
                    values.append(text)
                continue
            if not isinstance(sib, Tag):
                continue
            if sib.name and re.fullmatch(r"h[1-6]", sib.name):
                break
            if sib.name in {"table", "ul", "ol"}:
                # These are usually separate sections, not scalar field values.
                break
            text = clean_text(sib.get_text(" ", strip=True))
            if text:
                values.append(text)
        value = clean_text(" ".join(values))
        if not value:
            continue
        key_norm = norm_key(heading)
        alias = aliases.get(key_norm) or safe_col(heading)
        fields[alias] = value
        fields[safe_col(heading, prefix="raw_field")] = value
    return fields


def table_to_rows(table: Tag, base_url: str = BASE_URL) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    headers: list[str] = []
    for tr in table.find_all("tr"):
        cells = tr.find_all(["th", "td"])
        if not cells:
            continue
        if tr.find_all("th") and not tr.find_all("td"):
            headers = [clean_text(c.get_text(" ", strip=True)) for c in cells]
            continue
        if not headers:
            # Sometimes the first row contains th and td mixed; use text of th cells if present.
            ths = tr.find_all("th")
            if ths and len(ths) == len(cells):
                headers = [clean_text(c.get_text(" ", strip=True)) for c in ths]
                continue
            headers = [f"column_{i+1}" for i in range(len(cells))]
        row: dict[str, str] = {}
        for i, cell in enumerate(cells):
            header = headers[i] if i < len(headers) else f"column_{i+1}"
            text = clean_text(cell.get_text(" ", strip=True))
            row[header] = text
            links = [urljoin(base_url, a.get("href", "")) for a in cell.find_all("a", href=True)]
            if links:
                existing = row.get("_links", "")
                row["_links"] = " | ".join(x for x in [existing, *links] if x)
                if any("detail" in x for x in links):
                    row["_detail_url"] = next(x for x in links if "detail" in x)
        if any(clean_text(v) for k, v in row.items() if not k.startswith("_")):
            rows.append(row)
    return rows


def extract_section_tables(soup: BeautifulSoup, base_url: str = BASE_URL) -> dict[str, list[dict[str, str]]]:
    out: dict[str, list[dict[str, str]]] = {}
    current_section = "unknown"
    for node in soup.find_all(["h2", "table"]):
        if not isinstance(node, Tag):
            continue
        if node.name == "h2":
            current_section = clean_text(node.get_text(" ", strip=True)) or "unknown"
            continue
        if node.name == "table":
            rows = table_to_rows(node, base_url=base_url)
            if rows:
                key = section_key(current_section)
                out.setdefault(key, []).extend(rows)
    return out


def section_key(section_title: str) -> str:
    ns = norm_key(section_title)
    for key, names in SECTION_NAMES.items():
        if any(norm_key(name) == ns for name in names):
            return key
    return safe_col(section_title, prefix="section")


def extract_list_items(soup: BeautifulSoup, page_url: str) -> list[dict[str, str]]:
    items: dict[str, dict[str, str]] = {}
    anchors = soup.select('a[href*="detail-zakazky"]')
    for a in anchors:
        href = a.get("href", "")
        m = NEN_ID_URL_RE.search(href) or NEN_ID_DISPLAY_RE.search(href)
        if not m:
            continue
        url_id = display_id_to_url_id(m.group(0))
        detail_url = canonical_detail_url(url_id)
        row_node = a.find_parent("tr")
        row_text = clean_text(row_node.get_text(" ", strip=True)) if row_node else clean_text(a.parent.get_text(" ", strip=True) if a.parent else "")
        parsed = parse_list_row_text(row_text)
        parsed.update({"nen_url_id": url_id, "nen_system_number": url_id_to_display_id(url_id), "detail_url": detail_url, "source_list_url": page_url})
        items[url_id] = parsed
    if not items:
        # Fallback: parse visible lines from the page text.
        lines = get_visible_lines(soup)
        for line in lines:
            if "N006/" not in line and "N006-" not in line:
                continue
            m = NEN_ID_DISPLAY_RE.search(line)
            if not m:
                continue
            url_id = display_id_to_url_id(m.group(0))
            parsed = parse_list_row_text(line)
            parsed.update({"nen_url_id": url_id, "nen_system_number": url_id_to_display_id(url_id), "detail_url": canonical_detail_url(url_id), "source_list_url": page_url})
            items[url_id] = parsed
    return list(items.values())


def parse_list_row_text(text: str) -> dict[str, str]:
    text = clean_text(text)
    text = re.sub(r"^(Detail\s+)+", "", text, flags=re.I).strip()
    m = NEN_ID_DISPLAY_RE.search(text)
    out: dict[str, str] = {"list_row_text": text}
    if not m:
        return out
    out["nen_system_number"] = url_id_to_display_id(display_id_to_url_id(m.group(0)))
    after = text[m.end():].strip()
    statuses = [
        "Termination of performance", "Ukončení plnění", "Not terminated", "Neukončen",
        "Unsuccessful", "Neúspěšný", "Cancelled", "Zrušen", "Awarded", "Zadán", "Planned", "Plánován",
    ]
    found_status = ""
    found_idx = -1
    for status in statuses:
        idx = strip_accents(after.lower()).find(strip_accents(status.lower()))
        if idx >= 0 and (found_idx < 0 or idx < found_idx):
            found_status = status
            found_idx = idx
    if found_idx >= 0:
        out["list_tender_name_cs"] = clean_text(after[:found_idx])
        out["list_status_cs"] = found_status
        rest = clean_text(after[found_idx + len(found_status):])
        # Remove trailing Detail label if present.
        rest = re.sub(r"\bDetail\b\s*$", "", rest, flags=re.I).strip()
        # Split authority and deadline if a date is present at the end.
        dm = list(DATE_RE.finditer(rest))
        if dm:
            last = dm[-1]
            out["list_contracting_authority_cs"] = clean_text(rest[: last.start()])
            out["list_submission_deadline"] = clean_text(last.group(0))
        else:
            out["list_contracting_authority_cs"] = rest
    return out


def has_next_page(soup: BeautifulSoup, current_page: int) -> bool:
    target_patterns = [f"page={current_page + 1}", f"page%3D{current_page + 1}"]
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        text = clean_text(a.get_text(" ", strip=True))
        if any(p in href for p in target_patterns):
            return True
        if text in {f"Stránka {current_page + 1}", f"Page {current_page + 1}", str(current_page + 1)}:
            return True
    return False


def normalize_detail_fields(fields: dict[str, str]) -> dict[str, str]:
    row = dict(fields)
    for key in ["publication_date", "submission_deadline", "cancellation_date"]:
        if row.get(key):
            iso_dt, iso_date = parse_datetime(row[key])
            row[f"{key}_iso"] = iso_dt
            row[f"{key}_date"] = iso_date
    if row.get("estimated_value_excl_vat"):
        row["estimated_value_excl_vat_numeric"] = parse_decimal(row["estimated_value_excl_vat"])
    for key in [
        "awarded_on_basis_framework_agreement_cs", "awarded_in_dns_cs", "result_will_be_dns_cs",
        "is_framework_agreement_cs", "imported_public_contract_cs", "division_into_lots_cs",
    ]:
        if key in row:
            row[key] = as_boolish(row[key])
    return row


def normalize_table_row(row: dict[str, str], prefix: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in row.items():
        if k.startswith("_"):
            out[k] = v
            continue
        nk = norm_key(k)
        col = TABLE_COLUMN_ALIASES.get(nk) or safe_col(k, prefix=prefix)
        out[col] = clean_text(v)
    return out


TABLE_COLUMN_ALIASES = {
    # Contract result columns
    "evidencni cislo smlouvy": "contract_record_number",
    "contract registration number": "contract_record_number",
    "datum uzavreni smlouvy": "contract_signing_date",
    "date of conclusion of contract": "contract_signing_date",
    "uredni nazev": "supplier_name",
    "official name": "supplier_name",
    "smluvni cena s dph": "contract_price_vat_included",
    "contractual price incl vat": "contract_price_vat_included",
    "smluvni cena bez dph": "contract_price_vat_excluded",
    "contractual price excl vat": "contract_price_vat_excluded",
    "smluvni cena s dodatky s dph": "contract_price_with_amendments_vat_included",
    "contractual price with amendments incl vat": "contract_price_with_amendments_vat_included",
    "smluvni cena s dodatky bez dph": "contract_price_with_amendments_vat_excluded",
    "contractual price with amendments excl vat": "contract_price_with_amendments_vat_excluded",
    "mena": "currency",
    "currency": "currency",
    # Participants
    "obec": "municipality",
    "municipality": "municipality",
    "nabidkova cena s dph": "bid_price_vat_included",
    "tender price incl vat": "bid_price_vat_included",
    "nabidkova cena bez dph": "bid_price_vat_excluded",
    "tender price excl vat": "bid_price_vat_excluded",
    "dodavatel byl vybran": "supplier_selected",
    "economic operator selected": "supplier_selected",
    "s dodavatelem byla uzavrena smlouva nebo ramcova dohoda": "contract_or_framework_signed",
    "a contract or framework agreement was concluded with the economic operator": "contract_or_framework_signed",
    # Documents
    "evidencni cislo smlouvy dodatku": "contract_or_amendment_record_number",
    "soubor": "file_name",
    "file": "file_name",
    "typ dokumentu": "document_type_cs",
    "document type": "document_type_cs",
    "datum uverejneni": "publication_date",
    "date of publication": "publication_date",
    "antivirova kontrola": "antivirus_check_cs",
    "antivirus check": "antivirus_check_cs",
    # Publication records
    "uverejneni": "publication_cs",
    "publications": "publication_cs",
    "datum oduverejneni": "withdrawal_date",
    "date of withdrawal": "withdrawal_date",
    "oduverejnil": "withdrawn_by",
    "withdrawn by": "withdrawn_by",
    # Subject items
    "nazev polozky": "item_name_cs",
    "item name": "item_name_cs",
    "kod z cpv": "item_cpv_code",
    "cpv code": "item_cpv_code",
    "nazev z cpv": "item_cpv_name_cs",
    "cpv name": "item_cpv_name_cs",
    "popis polozky": "item_description_cs",
    "item description": "item_description_cs",
    # Place performance
    "kod": "code",
    "code": "code",
    "misto plneni": "place_of_performance_cs",
    "place of performance": "place_of_performance_cs",
}

# Extra aliases for subject item tables and item-detail fallback tables.
TABLE_COLUMN_ALIASES.update({
    "merna jednotka": "item_uom_cs",
    "měrná jednotka": "item_uom_cs",
    "unit of measure": "item_uom_cs",
    "unit": "item_uom_cs",
    "jednotka": "item_uom_cs",
    "mnozstvi": "item_quantity",
    "množství": "item_quantity",
    "quantity": "item_quantity",
    "predpokladane mnozstvi": "item_quantity",
    "předpokládané množství": "item_quantity",
    "estimated quantity": "item_quantity",
    "celkove mnozstvi": "item_quantity",
    "celkové množství": "item_quantity",
    "total quantity": "item_quantity",
    "hodnota polozky": "item_estimated_value",
    "hodnota položky": "item_estimated_value",
    "item value": "item_estimated_value",
    "predpokladana hodnota polozky": "item_estimated_value",
    "předpokládaná hodnota položky": "item_estimated_value",
    "estimated item value": "item_estimated_value",
})


def add_iso_dates_to_row(row: dict[str, str], date_keys: Iterable[str] = ("publication_date", "withdrawal_date", "contract_signing_date")) -> None:
    for key in date_keys:
        if row.get(key):
            iso_dt, iso_date = parse_datetime(row[key])
            row[f"{key}_iso"] = iso_dt
            row[f"{key}_date"] = iso_date


def add_numeric_prices(row: dict[str, str]) -> None:
    for key in [
        "contract_price_vat_included",
        "contract_price_vat_excluded",
        "contract_price_with_amendments_vat_included",
        "contract_price_with_amendments_vat_excluded",
        "bid_price_vat_included",
        "bid_price_vat_excluded",
    ]:
        if row.get(key):
            row[f"{key}_numeric"] = parse_decimal(row[key])


def parse_publication_records_fallback(soup: BeautifulSoup) -> list[dict[str, str]]:
    lines = get_visible_lines(soup)
    rows: list[dict[str, str]] = []
    in_section = False
    for line in lines:
        n = norm_key(line)
        if n in {norm_key(x) for x in SECTION_NAMES["publication_records"]}:
            in_section = True
            continue
        if in_section and n.startswith("evidence uverejneni ve vvz"):
            break
        if not in_section:
            continue
        if "Uveřejnění" not in line and "uverej" not in strip_accents(line.lower()) and "Publication" not in line:
            continue
        m = DATE_RE.search(line)
        if not m:
            continue
        date_text = clean_text(m.group(0))
        publication = clean_text(line[m.end():])
        publication = re.sub(r"^Detail\s+", "", publication, flags=re.I).strip()
        publication = re.sub(r"\s*Detail$", "", publication, flags=re.I).strip()
        if publication:
            row = {"publication_date": date_text, "publication_cs": publication}
            add_iso_dates_to_row(row, ["publication_date"])
            rows.append(row)
    return rows


def parse_result_fallback(soup: BeautifulSoup) -> dict[str, list[dict[str, str]]]:
    lines = get_visible_lines(soup)
    out = {"contracts": [], "participants": [], "documents": []}
    section = ""
    for line in lines:
        n = norm_key(line)
        if n in {norm_key(x) for x in SECTION_NAMES["contracts"]}:
            section = "contracts"
            continue
        if n in {norm_key(x) for x in SECTION_NAMES["documents"]}:
            section = "documents"
            continue
        if n in {norm_key(x) for x in SECTION_NAMES["participants"]}:
            section = "participants"
            continue
        if not section:
            continue
        if section == "contracts":
            row = parse_contract_result_line(line)
            if row:
                out["contracts"].append(row)
        elif section == "participants":
            row = parse_participant_line(line)
            if row:
                out["participants"].append(row)
    return out


def parse_contract_result_line(line: str) -> dict[str, str]:
    line = re.sub(r"^(Detail\s+)+", "", clean_text(line), flags=re.I)
    if not DATE_RE.search(line):
        return {}
    # Contract number, date, supplier, four prices, currency. Supplier may contain spaces.
    pattern = re.compile(
        r"^(?P<contract_record_number>.+?)\s+"
        r"(?P<contract_signing_date>\d{1,2}\.\s*\d{1,2}\.\s*\d{4})\s+"
        r"(?P<supplier_name>.+?)\s+"
        r"(?P<p1>[\d\s\u00a0.,]+)\s+"
        r"(?P<p2>[\d\s\u00a0.,]+)\s+"
        r"(?P<p3>[\d\s\u00a0.,]+)\s+"
        r"(?P<p4>[\d\s\u00a0.,]+)\s+"
        r"(?P<currency>[A-Z]{3})\b"
    )
    m = pattern.search(line)
    if not m:
        return {}
    row = {
        "contract_record_number": clean_text(m.group("contract_record_number")),
        "contract_signing_date": clean_text(m.group("contract_signing_date")),
        "supplier_name": clean_text(m.group("supplier_name")),
        "contract_price_vat_included": clean_text(m.group("p1")),
        "contract_price_vat_excluded": clean_text(m.group("p2")),
        "contract_price_with_amendments_vat_included": clean_text(m.group("p3")),
        "contract_price_with_amendments_vat_excluded": clean_text(m.group("p4")),
        "currency": clean_text(m.group("currency")),
    }
    add_iso_dates_to_row(row, ["contract_signing_date"])
    add_numeric_prices(row)
    return row


def parse_participant_line(line: str) -> dict[str, str]:
    line = re.sub(r"^(Detail\s+)+", "", clean_text(line), flags=re.I)
    if not re.search(r"\b(Ano|Ne|Yes|No)\b", line):
        return {}
    # More precise parse with prices.
    pattern = re.compile(
        r"^(?P<supplier_name>.+?)\s+"
        r"(?P<municipality>[\w\-.' /]+?)\s+"
        r"(?:(?P<p1>[\d\s\u00a0.,]+)\s+(?P<p2>[\d\s\u00a0.,]+)\s+(?P<currency>[A-Z]{3})\s+)?"
        r"(?P<selected>Ano|Ne|Yes|No)\s+(?P<signed>Ano|Ne|Yes|No)\b",
        re.I,
    )
    m = pattern.search(line)
    if not m:
        return {}
    row = {
        "supplier_name": clean_text(m.group("supplier_name")),
        "municipality": clean_text(m.group("municipality")),
        "supplier_selected": clean_text(m.group("selected")),
        "contract_or_framework_signed": clean_text(m.group("signed")),
    }
    if m.group("p1"):
        row["bid_price_vat_included"] = clean_text(m.group("p1"))
    if m.group("p2"):
        row["bid_price_vat_excluded"] = clean_text(m.group("p2"))
    if m.group("currency"):
        row["currency"] = clean_text(m.group("currency"))
    add_numeric_prices(row)
    return row


def get_result_publication_date(publication_rows: list[dict[str, str]]) -> tuple[str, str]:
    result_rows = []
    for row in publication_rows:
        pub = row.get("publication_cs", "")
        npub = norm_key(pub)
        if "vysledku" in npub or "result" in npub:
            result_rows.append(row)
    if not result_rows:
        return "", ""
    # If multiple results were published, use latest by ISO date as the current award/result publication.
    result_rows.sort(key=lambda r: r.get("publication_date_iso", ""), reverse=True)
    return result_rows[0].get("publication_date", ""), result_rows[0].get("publication_date_iso", "")


def get_first_publication_date(publication_rows: list[dict[str, str]], fallback: str = "") -> tuple[str, str]:
    dated = [r for r in publication_rows if r.get("publication_date_iso")]
    if not dated:
        iso, _ = parse_datetime(fallback)
        return fallback, iso
    dated.sort(key=lambda r: r.get("publication_date_iso", ""))
    return dated[0].get("publication_date", ""), dated[0].get("publication_date_iso", "")


def get_last_publication_date(publication_rows: list[dict[str, str]], fallback: str = "") -> tuple[str, str]:
    dated = [r for r in publication_rows if r.get("publication_date_iso")]
    if not dated:
        iso, _ = parse_datetime(fallback)
        return fallback, iso
    dated.sort(key=lambda r: r.get("publication_date_iso", ""), reverse=True)
    return dated[0].get("publication_date", ""), dated[0].get("publication_date_iso", "")


def parse_detail_page(fetcher: Fetcher, detail_url: str, nen_url_id: str) -> dict[str, Any]:
    html = fetcher.get(detail_url)
    soup = soup_from_html(html)
    fields = normalize_detail_fields(extract_h_fields(soup, FIELD_ALIASES))
    tables = extract_section_tables(soup, base_url=detail_url)
    publication_rows = [normalize_table_row(r, "publication") for r in tables.get("publication_records", [])]
    if not publication_rows:
        publication_rows = parse_publication_records_fallback(soup)
    for r in publication_rows:
        add_iso_dates_to_row(r, ["publication_date", "withdrawal_date"])
    place_rows = [normalize_table_row(r, "place") for r in tables.get("place_performance", [])]
    subject_item_rows = [normalize_table_row(r, "item") for r in tables.get("subject_items", [])]
    fields["nen_url_id"] = nen_url_id
    fields["nen_system_number"] = fields.get("nen_system_number") or url_id_to_display_id(nen_url_id)
    fields["detail_url"] = detail_url
    first_pub, first_pub_iso = get_first_publication_date(publication_rows, fields.get("publication_date", ""))
    last_pub, last_pub_iso = get_last_publication_date(publication_rows, fields.get("publication_date", ""))
    result_pub, result_pub_iso = get_result_publication_date(publication_rows)
    fields["first_publication_date"] = first_pub
    fields["first_publication_date_iso"] = first_pub_iso
    fields["last_publication_date"] = last_pub
    fields["last_publication_date_iso"] = last_pub_iso
    fields["award_result_publication_date"] = result_pub
    fields["award_result_publication_date_iso"] = result_pub_iso
    if place_rows:
        fields["place_performance_rows_json"] = json.dumps(place_rows, ensure_ascii=False)
        fields["place_performance_codes"] = " | ".join(clean_text(r.get("code", "")) for r in place_rows if r.get("code"))
        fields["place_performance_names_cs"] = " | ".join(clean_text(r.get("place_of_performance_cs", "")) for r in place_rows if r.get("place_of_performance_cs"))
    return {"fields": fields, "publication_rows": publication_rows, "place_rows": place_rows, "subject_item_rows": subject_item_rows, "soup": soup}


def parse_result_page(fetcher: Fetcher, result_url: str, nen_url_id: str) -> dict[str, list[dict[str, str]]]:
    try:
        html = fetcher.get(result_url)
    except Exception as exc:  # noqa: BLE001
        logging.warning("No result page or failed result page for %s: %s", nen_url_id, exc)
        return {"contracts": [], "participants": [], "documents": []}
    soup = soup_from_html(html)
    tables = extract_section_tables(soup, base_url=result_url)
    result: dict[str, list[dict[str, str]]] = {
        "contracts": [normalize_table_row(r, "contract") for r in tables.get("contracts", [])],
        "participants": [normalize_table_row(r, "participant") for r in tables.get("participants", [])],
        "documents": [normalize_table_row(r, "document") for r in tables.get("documents", [])],
    }
    if not any(result.values()):
        result = parse_result_fallback(soup)
    for collection in result.values():
        for row in collection:
            row["nen_url_id"] = nen_url_id
            row["nen_system_number"] = url_id_to_display_id(nen_url_id)
            row["result_url"] = result_url
            add_iso_dates_to_row(row, ["publication_date", "contract_signing_date"])
            add_numeric_prices(row)
            for k in ["supplier_selected", "contract_or_framework_signed"]:
                if k in row:
                    row[k] = as_boolish(row[k])
    return result


def canonical_documents_url(nen_url_id: str) -> str:
    return canonical_detail_url(nen_url_id).rstrip("/") + "/zadavaci-dokumentace"


def parse_documents_page(fetcher: Fetcher, documents_url: str, nen_url_id: str) -> list[dict[str, str]]:
    try:
        html = fetcher.get(documents_url)
    except Exception as exc:  # noqa: BLE001
        logging.warning("No documents page or failed documents page for %s: %s", nen_url_id, exc)
        return []
    soup = soup_from_html(html)
    tables = extract_section_tables(soup, base_url=documents_url)
    rows: list[dict[str, str]] = []
    for section_name, section_rows in tables.items():
        if "dokument" not in norm_key(section_name):
            continue
        for raw in section_rows:
            row = normalize_document_row(raw, nen_url_id, documents_url)
            if row.get("file_url") and row.get("file_name"):
                rows.append(row)
    return rows


def normalize_document_row(raw: dict[str, str], nen_url_id: str, documents_url: str) -> dict[str, str]:
    file_name = _first_nonempty(raw.get("Soubor"), raw.get("File"), raw.get("file_name"))
    document_type = _first_nonempty(raw.get("Typ dokumentu"), raw.get("Document type"), raw.get("document_type_cs"))
    publication_date = _first_nonempty(raw.get("Datum uveřejnění"), raw.get("Date of publication"), raw.get("publication_date"))
    links = raw.get("_links", "")
    file_url = ""
    for link in links.split(" | "):
        link = clean_text(link)
        if "/file?id=" in link:
            file_url = link
            break
    row = {
        "nen_url_id": nen_url_id,
        "nen_system_number": url_id_to_display_id(nen_url_id),
        "documents_url": documents_url,
        "file_name": clean_text(file_name),
        "document_type_cs": clean_text(document_type),
        "publication_date": clean_text(publication_date),
        "file_url": file_url,
        "_links": links,
    }
    add_iso_dates_to_row(row, ["publication_date"])
    return row


def is_spreadsheet_document(row: dict[str, str]) -> bool:
    name = clean_text(row.get("file_name", "")).lower()
    if not name.endswith((".xlsx", ".xls")) or name.endswith(".xlsm"):
        return False
    name_key = norm_key(name)
    non_item_markers = (
        "kryci list",
        "cover sheet",
        "cestne prohlaseni",
        "declaration",
        "plna moc",
        "power of attorney",
        "navrh smlouvy",
        "smlouva",
        "contract",
        "identifikacni udaje",
        "qualification",
    )
    if any(marker in name_key for marker in non_item_markers):
        item_markers = (
            "specifikace",
            "cenik",
            "cenova nabidka",
            "rozpocet",
            "polozk",
            "vykaz vymer",
            "kazdorocni",
        )
        return any(marker in name_key for marker in item_markers)
    return True


def parse_spreadsheet_item_rows(fetcher: Fetcher, document: dict[str, str], tender: dict[str, Any]) -> list[dict[str, str]]:
    if pd is None or not is_spreadsheet_document(document):
        return []
    file_url = document.get("file_url", "")
    if not file_url:
        return []
    suffix = ".xlsx" if document.get("file_name", "").lower().endswith(".xlsx") else ".xls"
    try:
        data = fetcher.get_bytes(file_url, suffix=suffix)
        excel = pd.ExcelFile(BytesIO(data))  # type: ignore[arg-type]
    except Exception as exc:  # noqa: BLE001
        logging.warning("Failed to open spreadsheet document for %s (%s): %s", tender.get("nen_url_id"), document.get("file_name"), exc)
        return []
    rows: list[dict[str, str]] = []
    for sheet_name in excel.sheet_names:
        try:
            df = pd.read_excel(excel, sheet_name=sheet_name, header=None, dtype=object)  # type: ignore[arg-type]
        except Exception as exc:  # noqa: BLE001
            logging.warning("Failed to read sheet %s from %s: %s", sheet_name, document.get("file_name"), exc)
            continue
        for row_idx, values in df.iterrows():
            item = spreadsheet_row_to_item(values.tolist(), tender, document, sheet_name, int(row_idx) + 1)
            if item and is_medical_item_row(tender, item):
                rows.append(item)
    return rows


def spreadsheet_row_to_item(values: list[Any], tender: dict[str, Any], document: dict[str, str], sheet_name: str, row_number: int) -> dict[str, str]:
    cells = [clean_text(v) for v in values]
    if not any(cells):
        return {}
    item_no_index = -1
    for idx, cell in enumerate(cells[:4]):
        if re.fullmatch(r"\d{1,4}[.)]?", cell):
            item_no_index = idx
            break
    if item_no_index < 0:
        return {}
    item_no = cells[item_no_index].rstrip(".)")
    candidates = [(idx, cell) for idx, cell in enumerate(cells[item_no_index + 1 :], start=item_no_index + 1) if len(cell) >= 8]
    if not candidates:
        return {}
    desc_idx, desc = max(candidates, key=lambda x: len(x[1]))
    qty = ""
    uom = ""
    for idx in range(desc_idx + 1, len(cells)):
        cell = cells[idx]
        if not cell:
            continue
        if not qty and re.fullmatch(r"\d+(?:[.,]\d+)?", cell):
            qty = cell
            continue
        if qty and not uom and re.fullmatch(r"[A-Za-zÁ-ž]{1,12}", cell):
            uom = cell
            break
    if not qty:
        for idx in range(item_no_index + 1, len(cells)):
            cell = cells[idx]
            if idx == desc_idx or not cell:
                continue
            if re.fullmatch(r"\d+(?:[.,]\d+)?", cell):
                qty = cell
                break
    return {
        "nen_url_id": tender.get("nen_url_id", ""),
        "nen_system_number": tender.get("nen_system_number", ""),
        "item_sequence": item_no,
        "item_name_cs": desc[:180],
        "item_description_cs": desc,
        "item_quantity": qty,
        "item_uom_cs": uom,
        "item_source": "tender_document_spreadsheet",
        "item_source_file": document.get("file_name", ""),
        "item_source_url": document.get("file_url", ""),
        "item_source_sheet": sheet_name,
        "item_source_row": str(row_number),
        "item_cpv_code": tender.get("cpv_code", ""),
        "item_cpv_name_cs": tender.get("cpv_name_cs", ""),
    }


def extract_document_item_rows(fetcher: Fetcher, tender: dict[str, Any]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    documents = parse_documents_page(fetcher, canonical_documents_url(tender.get("nen_url_id", "")), tender.get("nen_url_id", ""))
    item_rows: list[dict[str, str]] = []
    for document in documents:
        item_rows.extend(parse_spreadsheet_item_rows(fetcher, document, tender))
    return item_rows, documents


def parse_item_detail_page(fetcher: Fetcher, url: str, nen_url_id: str) -> dict[str, str]:
    try:
        html = fetcher.get(url)
        soup = soup_from_html(html)
        fields = extract_h_fields(soup, ITEM_FIELD_ALIASES)
    except Exception as exc:  # noqa: BLE001
        logging.warning("Failed item detail for %s: %s", url, exc)
        fields = {"item_detail_error": str(exc)}
    fields["nen_url_id"] = nen_url_id
    fields["nen_system_number"] = url_id_to_display_id(nen_url_id)
    fields["item_detail_url"] = url
    return fields


def enrich_subject_items(fetcher: Fetcher, item_rows: list[dict[str, str]], nen_url_id: str) -> list[dict[str, str]]:
    enriched: list[dict[str, str]] = []
    for idx, row in enumerate(item_rows, start=1):
        base = dict(row)
        base["nen_url_id"] = nen_url_id
        base["nen_system_number"] = url_id_to_display_id(nen_url_id)
        base["item_sequence"] = str(idx)
        detail_url = row.get("_detail_url") or ""
        if not detail_url:
            links = row.get("_links", "")
            for link in links.split(" | "):
                if "detail-polozka" in link or "detail-item" in link:
                    detail_url = link
                    break
        if detail_url and ("detail-polozka" in detail_url or "detail-item" in detail_url):
            detail_fields = parse_item_detail_page(fetcher, detail_url, nen_url_id)
            # Prefer explicit detail fields where present but preserve row fields too.
            base.update({k: v for k, v in detail_fields.items() if v})
        enriched.append(base)
    return enriched


def add_translations(rows: list[dict[str, str]], columns: list[str], translator: Translator, suffix_from: str = "_cs", suffix_to: str = "_en") -> None:
    if translator.mode == "none":
        for row in rows:
            for col in columns:
                target = col[:-len(suffix_from)] + suffix_to if col.endswith(suffix_from) else f"{col}{suffix_to}"
                row.setdefault(target, "")
        return
    for row in rows:
        for col in columns:
            target = col[:-len(suffix_from)] + suffix_to if col.endswith(suffix_from) else f"{col}{suffix_to}"
            row[target] = translator.translate(row.get(col, "")) if row.get(col) else ""


def row_with_context(row: dict[str, str], tender: dict[str, str]) -> dict[str, str]:
    context = {
        "nen_url_id": tender.get("nen_url_id", ""),
        "nen_system_number": tender.get("nen_system_number", ""),
        "tender_name_cs": tender.get("tender_name_cs", ""),
        "tender_name_en": tender.get("tender_name_en", ""),
        "contracting_authority_cs": tender.get("contracting_authority_cs", ""),
        "publication_date": tender.get("publication_date", ""),
        "publication_date_iso": tender.get("publication_date_iso", ""),
        "award_result_publication_date": tender.get("award_result_publication_date", ""),
        "award_result_publication_date_iso": tender.get("award_result_publication_date_iso", ""),
        "detail_url": tender.get("detail_url", ""),
    }
    context.update(row)
    return context


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return
    columns = collect_columns(rows)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in columns})


def collect_columns(rows: list[dict[str, Any]]) -> list[str]:
    preferred = [
        # User-friendly flat-output columns first.
        "notice_id", "notice_url", "result_url", "source_system", "country", "language",
        "title", "title_en", "description", "description_en", "buyer", "buyer_en",
        "classification_code", "classification", "classification_en", "status", "status_en",
        "publication_date", "publication_date_iso", "awarded_date", "awarded_date_iso",
        "award_result_publication_date", "award_result_publication_date_iso",
        "awarding_supplier", "awarded_supplier", "contract_record_number", "contract_signing_date", "contract_signing_date_iso",
        "currency", "amount", "amount_text", "amount_vat_excluded", "amount_vat_included",
        "contract_price_vat_excluded", "contract_price_vat_excluded_numeric", "contract_price_vat_included", "contract_price_vat_included_numeric",
        "item_no", "item_name", "item_name_en", "item_description", "item_description_en", "item_cpv_code", "item_cpv_name", "item_cpv_name_en",
        "item_uom", "item_uom_en", "item_quantity", "item_estimated_value",
        "notice_source_query", "query_text", "matched_queries", "scraped_at", "dedup_key",
        "participants_json", "publication_records_json", "documents_json", "document_urls",
        # Original/detail-sheet columns next.
        "nen_system_number", "nen_url_id", "tender_name_cs", "tender_name_en", "status_cs", "status_en",
        "contracting_authority_cs", "contracting_authority_en", "first_publication_date", "first_publication_date_iso", "last_publication_date", "last_publication_date_iso",
        "supplier_name", "cpv_code", "cpv_name_cs", "cpv_name_en",
        "nipez_code", "nipez_name_cs", "nipez_name_en", "subject_description_cs", "subject_description_en", "detail_url",
    ]
    seen: set[str] = set()
    cols: list[str] = []
    for col in preferred:
        if any(col in row for row in rows):
            cols.append(col)
            seen.add(col)
    for row in rows:
        for col in row.keys():
            if col not in seen and not col.startswith("raw_field_"):
                cols.append(col)
                seen.add(col)
    for row in rows:
        for col in row.keys():
            if col not in seen:
                cols.append(col)
                seen.add(col)
    return cols


def write_excel(path: Path, sheets: dict[str, list[dict[str, Any]]]) -> None:
    if pd is None:
        logging.warning("pandas is not installed; skipping XLSX export. Install with: pip install pandas openpyxl")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:  # type: ignore[call-arg]
        for sheet_name, rows in sheets.items():
            safe_name = sheet_name[:31]
            if sheet_name == "Item_Details":
                cols = REQUESTED_ITEM_EXPORT_COLUMNS
                df = pd.DataFrame(rows, columns=cols)
            elif rows:
                cols = collect_columns(rows)
                df = pd.DataFrame(rows, columns=cols)
            else:
                df = pd.DataFrame()
            df.to_excel(writer, sheet_name=safe_name, index=False)
            ws = writer.sheets[safe_name]
            try:
                ws.freeze_panes = "A2"
                for idx, col in enumerate(df.columns, start=1):
                    max_len = max([len(str(col))] + [len(str(v)) for v in df[col].head(200).fillna("").tolist()])
                    ws.column_dimensions[ws.cell(row=1, column=idx).column_letter].width = min(max(max_len + 2, 10), 55)
                ws.auto_filter.ref = ws.dimensions
            except Exception:
                pass


def _row_group_key(row: dict[str, Any]) -> str:
    return clean_text(row.get("nen_url_id", "")) or display_id_to_url_id(clean_text(row.get("nen_system_number", "")))


def _group_rows_by_tender(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        key = _row_group_key(row)
        if key:
            grouped.setdefault(key, []).append(row)
    return grouped


def _unique_join(rows: list[dict[str, Any]], key: str, sep: str = " | ") -> str:
    values: list[str] = []
    for row in rows:
        value = clean_text(row.get(key, ""))
        if value and value not in values:
            values.append(value)
    return sep.join(values)


def _json_rows(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    return json.dumps(rows, ensure_ascii=False, default=str)


def _prefixed_columns(row: dict[str, Any], prefix: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in row.items():
        if key in {"participants_json", "publication_records_json", "documents_json"}:
            continue
        safe_key = re.sub(r"[^A-Za-z0-9_]+", "_", str(key)).strip("_") or "field"
        col = f"{prefix}_{safe_key}"
        out[col] = value
    return out


def _first_nonempty(*values: Any) -> str:
    for value in values:
        text = clean_text(value)
        if text:
            return text
    return ""


def _make_dedup_key(tender: dict[str, Any], contract: dict[str, Any], item: dict[str, Any]) -> str:
    parts = [
        _first_nonempty(tender.get("nen_system_number"), tender.get("nen_url_id")),
        _first_nonempty(contract.get("contract_record_number"), contract.get("supplier_name")),
        _first_nonempty(item.get("item_sequence"), item.get("item_name_cs"), item.get("item_description_cs")),
    ]
    return hashlib.sha256("||".join(parts).encode("utf-8", "ignore")).hexdigest()[:24]


def build_all_columns_rows(
    tenders: list[dict[str, Any]],
    contracts: list[dict[str, Any]],
    participants: list[dict[str, Any]],
    publication_records: list[dict[str, Any]],
    subject_items: list[dict[str, Any]],
    documents: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Flatten all scraped data into one Excel-friendly table.

    Output grain: one row per accepted tender x awarded contract x subject item.
    This keeps every item row visible while repeating tender/contract fields as needed.
    Multi-row supporting sections (participants, publication records, documents) are kept as
    JSON plus delimited summary columns so no scraped details are lost in the single-sheet output.
    """
    contracts_by = _group_rows_by_tender(contracts)
    participants_by = _group_rows_by_tender(participants)
    pubs_by = _group_rows_by_tender(publication_records)
    items_by = _group_rows_by_tender(subject_items)
    docs_by = _group_rows_by_tender(documents)
    scraped_at = dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    flat_rows: list[dict[str, Any]] = []

    for tender in tenders:
        tender_key = _row_group_key(tender)
        contract_rows = contracts_by.get(tender_key, []) or [{}]
        item_rows = items_by.get(tender_key, []) or [{}]
        participant_rows = participants_by.get(tender_key, [])
        pub_rows = pubs_by.get(tender_key, [])
        doc_rows = docs_by.get(tender_key, [])

        for contract_index, contract in enumerate(contract_rows, start=1):
            for item_index, item in enumerate(item_rows, start=1):
                amount_numeric = _first_nonempty(
                    contract.get("contract_price_vat_excluded_numeric"),
                    contract.get("contract_price_vat_included_numeric"),
                    tender.get("estimated_value_excl_vat_numeric"),
                )
                amount_text = _first_nonempty(
                    contract.get("contract_price_vat_excluded"),
                    contract.get("contract_price_vat_included"),
                    tender.get("estimated_value_excl_vat"),
                )
                supplier = _first_nonempty(contract.get("supplier_name"), tender.get("selected_suppliers"))
                item_name = _first_nonempty(item.get("item_name_cs"), item.get("subject_matter_name_cs"))
                item_description = _first_nonempty(item.get("item_description_cs"), item_name)
                item_name_en = _first_nonempty(item.get("item_name_en"), item.get("subject_matter_name_en"))
                item_description_en = _first_nonempty(item.get("item_description_en"), item_name_en)
                publication_date = _first_nonempty(tender.get("publication_date"), tender.get("first_publication_date"))
                publication_date_iso = _first_nonempty(tender.get("publication_date_iso"), tender.get("first_publication_date_iso"))
                awarded_date = _first_nonempty(tender.get("awarded_date"), tender.get("award_result_publication_date"), contract.get("contract_signing_date"))
                awarded_date_iso = _first_nonempty(tender.get("awarded_date_iso"), tender.get("award_result_publication_date_iso"), contract.get("contract_signing_date_iso"))

                row: dict[str, Any] = {
                    "notice_id": _first_nonempty(tender.get("nen_system_number"), tender.get("nen_url_id")),
                    "notice_url": tender.get("detail_url", ""),
                    "result_url": _first_nonempty(contract.get("result_url"), canonical_result_url(tender_key) if tender_key else ""),
                    "source_system": "Czech NEN",
                    "country": "Czechia",
                    "language": "cs",
                    "title": _first_nonempty(tender.get("tender_name_cs"), tender.get("list_tender_name_cs")),
                    "title_en": tender.get("tender_name_en", ""),
                    "description": _first_nonempty(tender.get("subject_description_cs"), tender.get("subject_matter_name_cs"), tender.get("tender_name_cs")),
                    "description_en": _first_nonempty(tender.get("subject_description_en"), tender.get("subject_matter_name_en"), tender.get("tender_name_en")),
                    "buyer": _first_nonempty(tender.get("contracting_authority_cs"), tender.get("list_contracting_authority_cs")),
                    "buyer_en": tender.get("contracting_authority_en", ""),
                    "classification_code": _first_nonempty(tender.get("cpv_code"), tender.get("nipez_code")),
                    "classification": _first_nonempty(tender.get("cpv_name_cs"), tender.get("nipez_name_cs")),
                    "classification_en": _first_nonempty(tender.get("cpv_name_en"), tender.get("nipez_name_en")),
                    "status": _first_nonempty(tender.get("status_cs"), tender.get("list_status_cs")),
                    "status_en": tender.get("status_en", ""),
                    "publication_date": publication_date,
                    "publication_date_iso": publication_date_iso,
                    "awarded_date": awarded_date,
                    "awarded_date_iso": awarded_date_iso,
                    "award_result_publication_date": tender.get("award_result_publication_date", ""),
                    "award_result_publication_date_iso": tender.get("award_result_publication_date_iso", ""),
                    "awarding_supplier": supplier,
                    "awarded_supplier": supplier,
                    "contract_record_number": contract.get("contract_record_number", ""),
                    "contract_signing_date": contract.get("contract_signing_date", ""),
                    "contract_signing_date_iso": contract.get("contract_signing_date_iso", ""),
                    "currency": _first_nonempty(contract.get("currency"), tender.get("currency_cs"), tender.get("currency")),
                    "amount": amount_numeric,
                    "amount_text": amount_text,
                    "amount_vat_excluded": _first_nonempty(contract.get("contract_price_vat_excluded_numeric"), contract.get("contract_price_vat_excluded")),
                    "amount_vat_included": _first_nonempty(contract.get("contract_price_vat_included_numeric"), contract.get("contract_price_vat_included")),
                    "contract_price_vat_excluded": contract.get("contract_price_vat_excluded", ""),
                    "contract_price_vat_excluded_numeric": contract.get("contract_price_vat_excluded_numeric", ""),
                    "contract_price_vat_included": contract.get("contract_price_vat_included", ""),
                    "contract_price_vat_included_numeric": contract.get("contract_price_vat_included_numeric", ""),
                    "item_no": _first_nonempty(item.get("item_sequence"), str(item_index) if item else ""),
                    "item_name": item_name,
                    "item_name_en": item_name_en,
                    "item_description": item_description,
                    "item_description_en": item_description_en,
                    "item_cpv_code": item.get("item_cpv_code", ""),
                    "item_cpv_name": item.get("item_cpv_name_cs", ""),
                    "item_cpv_name_en": item.get("item_cpv_name_en", ""),
                    "item_uom": _first_nonempty(item.get("item_uom_cs"), item.get("item_uom"), item.get("unit_of_measure")),
                    "item_uom_en": item.get("item_uom_en", ""),
                    "item_quantity": _first_nonempty(item.get("item_quantity"), item.get("quantity")),
                    "item_estimated_value": item.get("item_estimated_value", ""),
                    "notice_source_query": tender.get("matched_queries", ""),
                    "query_text": tender.get("matched_queries", ""),
                    "matched_queries": tender.get("matched_queries", ""),
                    "scraped_at": scraped_at,
                    "dedup_key": _make_dedup_key(tender, contract, item),
                    "contract_row_index": contract_index if contract else "",
                    "item_row_index": item_index if item else "",
                    "participant_count": len(participant_rows),
                    "publication_record_count": len(pub_rows),
                    "document_count": len(doc_rows),
                    "participant_names": _unique_join(participant_rows, "supplier_name"),
                    "publication_record_names": _unique_join(pub_rows, "publication_cs"),
                    "publication_record_dates": _unique_join(pub_rows, "publication_date"),
                    "document_names": _unique_join(doc_rows, "file_name"),
                    "document_types": _unique_join(doc_rows, "document_type_cs"),
                    "document_publication_dates": _unique_join(doc_rows, "publication_date"),
                    "document_urls": _unique_join(doc_rows, "_links"),
                    "participants_json": _json_rows(participant_rows),
                    "publication_records_json": _json_rows(pub_rows),
                    "documents_json": _json_rows(doc_rows),
                }
                # Add original columns with clear prefixes so no source field is lost or overwritten.
                row.update(_prefixed_columns(tender, "tender"))
                if contract:
                    row.update(_prefixed_columns(contract, "contract"))
                if item:
                    row.update(_prefixed_columns(item, "item_detail"))
                flat_rows.append(row)

    return flat_rows



# Final requested export columns only.
# These are the columns shown/requested by the user, keeping one row per tender/contract/item.
REQUESTED_ITEM_EXPORT_COLUMNS = [
    "title_en",
    "description",
    "description_en",
    "buyer",
    "buyer_en",
    "classification_code",
    "classification",
    "classification_en",
    "status",
    "status_en",
    "currency",
    "amount",
    "awarding_supplier",
    "awarded_date",
    "awarded_date_iso",
    "contract_record_number",
    "contract_signing_date",
    "item_no",
    "item_description",
    "item_description_en",
    "item_uom",
    "item_uom_en",
    "item_quantity",
    "notice_id",
    "notice_url",
    "query_text",
    "scraped_at",
    "dedup_key",
]


ITEM_DETAIL_REQUIRED_COLUMNS = ["item_description", "item_uom", "item_quantity"]


def has_required_item_detail(row: dict[str, Any]) -> bool:
    return any(clean_text(row.get(col, "")) for col in ITEM_DETAIL_REQUIRED_COLUMNS)


def project_requested_item_columns(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only rows where public NEN item details are present."""
    projected: list[dict[str, Any]] = []
    for row in rows:
        if not has_required_item_detail(row):
            continue
        projected.append({col: row.get(col, "") for col in REQUESTED_ITEM_EXPORT_COLUMNS})
    return projected


def log_jsonl(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")


def load_queries(args: argparse.Namespace) -> list[str]:
    queries: list[str] = []
    if args.queries_file:
        qpath = Path(args.queries_file)
        queries.extend([clean_text(x) for x in qpath.read_text(encoding="utf-8").splitlines() if clean_text(x) and not clean_text(x).startswith("#")])
    if args.query:
        queries.extend(args.query)
    if not queries:
        queries.extend(DEFAULT_QUERIES)
    # De-duplicate preserving order.
    seen: set[str] = set()
    out: list[str] = []
    for q in queries:
        key = strip_accents(q.lower())
        if key not in seen:
            out.append(q)
            seen.add(key)
    return out


def discover_tenders(fetcher: Fetcher, queries: list[str], max_pages_per_query: int, log_path: Path) -> dict[str, dict[str, str]]:
    tenders: dict[str, dict[str, str]] = {}
    for query in queries:
        logging.info("Searching query: %s", query)
        repeated_empty = 0
        for page in range(1, max_pages_per_query + 1):
            url = build_search_url(query, page)
            logging.info("Advanced awarded search URL: %s", url) if getattr(fetcher, "debug_url_log", False) else logging.debug("Advanced awarded search URL: %s", url)
            try:
                html = fetcher.get(url)
            except Exception as exc:  # noqa: BLE001
                log_jsonl(log_path, {"level": "error", "stage": "search", "query": query, "page": page, "url": url, "error": str(exc)})
                break
            soup = soup_from_html(html)
            items = extract_list_items(soup, url)
            logging.debug("Parsed search page query=%r page=%s result_items=%s", query, page, len(items))
            new_count = 0
            for item in items:
                nen_url_id = item.get("nen_url_id", "")
                if not nen_url_id:
                    continue
                if nen_url_id not in tenders:
                    tenders[nen_url_id] = item
                    new_count += 1
                else:
                    # Record all query terms that found this tender.
                    existing_q = tenders[nen_url_id].get("matched_queries", "")
                    parts = [x for x in existing_q.split(" | ") if x]
                    if query not in parts:
                        parts.append(query)
                    tenders[nen_url_id]["matched_queries"] = " | ".join(parts)
            logging.info("Query=%r page=%s items=%s new=%s total=%s", query, page, len(items), new_count, len(tenders))
            for item in items:
                item.setdefault("matched_queries", query)
            log_jsonl(log_path, {"level": "info", "stage": "search", "query": query, "page": page, "items": len(items), "new": new_count, "total": len(tenders), "url": url})
            if not items or new_count == 0:
                repeated_empty += 1
            else:
                repeated_empty = 0
            if repeated_empty >= 2:
                logging.debug("Stopping query=%r at page=%s because two pages had no new items", query, page)
                break
            if not has_next_page(soup, page) and page > 1:
                logging.debug("Stopping query=%r at page=%s because there is no next page link", query, page)
                break
    return tenders


def within_date_range(row: dict[str, str], start_date: dt.date, end_date: dt.date) -> bool:
    date_str = row.get("publication_date_date") or row.get("publication_date_iso", "")[:10]
    if not date_str and row.get("first_publication_date_iso"):
        date_str = row["first_publication_date_iso"][:10]
    if not date_str:
        return False
    try:
        d = dt.date.fromisoformat(date_str)
    except ValueError:
        return False
    return start_date <= d <= end_date


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    today = dt.date.today().isoformat()
    parser = argparse.ArgumentParser(description="Scrape awarded Czech NEN medical/healthcare tenders from public no-JS pages.")
    parser.add_argument("--start-date", default="2024-01-01", help="Publication date lower bound, ISO YYYY-MM-DD. Default: 2024-01-01")
    parser.add_argument("--end-date", default=today, help=f"Publication date upper bound, ISO YYYY-MM-DD. Default: {today}")
    parser.add_argument("--output-dir", default="nen_awarded_healthcare_output", help="Directory for CSV/XLSX/log outputs.")
    parser.add_argument("--query", action="append", help="Add a NEN quick-search term. Repeat to add multiple terms. Defaults to built-in medical/healthcare terms.")
    parser.add_argument("--queries-file", help="Text file with one query term per line.")
    parser.add_argument("--max-pages-per-query", type=int, default=250, help="Safety cap for pages per query. Default: 250")
    parser.add_argument("--max-tenders", type=int, default=0, help="Stop after this many accepted tenders. 0 means no cap.")
    parser.add_argument("--translate", default="google", choices=["google", "google-public", "none", "same"], help="Translation mode. Default: google public endpoint.")
    parser.add_argument("--translation-delay", type=float, default=0.15, help="Delay between translation calls. Default: 0.15s")
    parser.add_argument("--request-delay", type=float, default=0.45, help="Delay between NEN requests. Default: 0.45s")
    parser.add_argument("--timeout", type=int, default=40, help="HTTP timeout seconds. Default: 40")
    parser.add_argument("--retries", type=int, default=7, help="HTTP retry attempts for NEN HTML and file downloads. Default: 7")
    parser.add_argument("--cache", default="", help="Optional cache directory for fetched HTML pages.")
    parser.add_argument("--include-non-medical-keyword-hits", action="store_true", help="Keep records found by medical query terms even when CPV/text medical predicate fails.")
    parser.add_argument("--include-status", action="append", help="Advanced override only: additional DETAIL PAGE current status text to include. Default is strict Awarded/Zadán only.")
    parser.add_argument("--no-xlsx", action="store_true", help="Skip XLSX export. Mainly useful for debugging only.")
    parser.add_argument("--all-columns-filename", default="czechia_nen_awarded_healthcare_item_details_only.xlsx", help="Single-sheet Excel filename. Default: czechia_nen_awarded_healthcare_item_details_only.xlsx")
    parser.add_argument("--write-csv", action="store_true", help="Also write all_columns.csv. Default is one Excel file plus logs only.")
    parser.add_argument("--write-detail-sheets", action="store_true", help="Also write the old multi-sheet audit workbook. Default is off.")
    parser.add_argument("--verbose", action="store_true", help="Verbose logging. Same as --debug for progress visibility.")
    parser.add_argument("--debug", action="store_true", help="Detailed debug logging: URLs fetched, cache hits, page progress, skip reasons, and output file paths.")
    parser.add_argument("--progress-every", type=int, default=10, help="Print a progress summary every N candidate tenders during detail scraping. Use 1 for every tender. Default: 10")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    debug_enabled = bool(args.verbose or args.debug)
    log_level = logging.DEBUG if debug_enabled else logging.INFO
    logging.basicConfig(level=log_level, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout, force=True)

    if args.include_status:
        for status in args.include_status:
            AWARDED_STATUSES.add(status)
    start_date = dt.date.fromisoformat(args.start_date)
    end_date = dt.date.fromisoformat(args.end_date)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    debug_log_path = output_dir / "scrape_debug.log"
    file_handler = logging.FileHandler(debug_log_path, encoding="utf-8")
    file_handler.setLevel(log_level)
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.getLogger().addHandler(file_handler)

    logging.info("START NEN healthcare awarded tender scrape")
    logging.info("ADVANCED SEARCH FILTER: every list URL includes Current status = Awarded/Zadán (stavZP=zadana).")
    logging.info("STRICT STATUS CHECK: detail page current status must still be Awarded/Zadán. Termination of performance is excluded.")
    logging.info("DATE RANGE publication_date=%s to %s", args.start_date, args.end_date)
    logging.info("OUTPUT DIR %s", output_dir.resolve())
    logging.info("TRANSLATE mode=%s", args.translate)
    logging.info("DEBUG LOG %s", debug_log_path.resolve())
    if debug_enabled:
        logging.debug("DEBUG mode is ON. URLs, cache hits, skip reasons, and write paths will be shown.")

    log_path = output_dir / "scrape_log.jsonl"
    if log_path.exists():
        log_path.unlink()


    queries = load_queries(args)
    logging.info("NEN healthcare awarded scraper started | date_range=%s to %s | output_dir=%s | translate=%s | request_delay=%ss", args.start_date, args.end_date, output_dir, args.translate, args.request_delay)
    logging.info("Loaded %s search query terms. First terms: %s", len(queries), ", ".join(queries[:8]))
    (output_dir / "queries_used.txt").write_text("\n".join(queries) + "\n", encoding="utf-8")
    fetcher = Fetcher(timeout=args.timeout, retries=args.retries, delay=args.request_delay, cache_dir=Path(args.cache) if args.cache else output_dir / "html_cache")
    translator = Translator(args.translate, output_dir / "translation_cache.json", delay=args.translation_delay)

    log_jsonl(log_path, {"level": "info", "stage": "start", "start_date": args.start_date, "end_date": args.end_date, "queries": queries})
    logging.info("Discovery phase started. You should see one line per search page.")
    discovered = discover_tenders(fetcher, queries, args.max_pages_per_query, log_path)
    logging.info("Discovery phase finished: %s unique candidate tender IDs", len(discovered))

    tenders: list[dict[str, str]] = []
    contracts: list[dict[str, str]] = []
    participants: list[dict[str, str]] = []
    publication_records: list[dict[str, str]] = []
    subject_items: list[dict[str, str]] = []
    documents: list[dict[str, str]] = []

    candidate_ids = list(discovered.keys())
    logging.info("Detail phase started: %s candidate tenders will be checked.", len(candidate_ids))
    if args.max_tenders and args.max_tenders > 0:
        logging.info("Accepted-tender cap enabled: stopping after %s accepted tenders.", args.max_tenders)

    for idx, nen_url_id in enumerate(candidate_ids, start=1):
        seed = discovered[nen_url_id]
        detail_url = seed.get("detail_url") or canonical_detail_url(nen_url_id)
        logging.info("[%s/%s] Detail %s", idx, len(candidate_ids), nen_url_id)
        if args.progress_every and args.progress_every > 0 and (idx == 1 or idx % args.progress_every == 0):
            logging.info("Progress heartbeat: checked=%s/%s accepted=%s contracts=%s subject_items=%s", idx - 1, len(candidate_ids), len(tenders), len(contracts), len(subject_items))
        try:
            parsed = parse_detail_page(fetcher, detail_url, nen_url_id)
            tender = {**seed, **parsed["fields"]}
            logging.debug("Parsed detail %s | name=%r | status=%r | publication_date=%r | cpv=%r", nen_url_id, tender.get("tender_name_cs", ""), tender.get("status_cs", ""), tender.get("publication_date", ""), tender.get("cpv_code", ""))
            # IMPORTANT: User requested only tenders whose tender page shows:
            # CURRENT STATUS OF THE PROCUREMENT PROCEDURE = Awarded.
            # Therefore we filter using the parsed detail-page field status_cs only.
            detail_current_status = tender.get("status_cs", "")
            if not is_awarded_status(detail_current_status):
                logging.debug("Skipping %s because DETAIL PAGE current status is not Awarded/Zadán: %r", nen_url_id, detail_current_status)
                log_jsonl(log_path, {"level": "info", "stage": "skip", "reason": "detail_current_status_not_awarded", "nen_url_id": nen_url_id, "detail_current_status": detail_current_status})
                continue
            if not within_date_range(tender, start_date, end_date):
                logging.debug("Skipping %s because publication date is outside range: %r", nen_url_id, tender.get("publication_date", ""))
                log_jsonl(log_path, {"level": "info", "stage": "skip", "reason": "publication_date", "nen_url_id": nen_url_id, "publication_date": tender.get("publication_date", "")})
                continue
            if not args.include_non_medical_keyword_hits and not is_medical_record(tender):
                logging.debug("Skipping %s because it did not match medical/healthcare filter: cpv=%r name=%r", nen_url_id, tender.get("cpv_code", ""), tender.get("tender_name_cs", ""))
                log_jsonl(log_path, {"level": "info", "stage": "skip", "reason": "medical_filter", "nen_url_id": nen_url_id, "cpv": tender.get("cpv_code", ""), "name": tender.get("tender_name_cs", "")})
                continue

            item_rows = enrich_subject_items(fetcher, parsed["subject_item_rows"], nen_url_id)
            document_item_rows, tender_documents = extract_document_item_rows(fetcher, tender)
            if document_item_rows:
                logging.info("Using %s spreadsheet item rows for %s from public tender documents", len(document_item_rows), nen_url_id)
                item_rows = document_item_rows
            if not item_rows:
                logging.debug("Skipping %s because no public subject-item rows were exposed on the detail page", nen_url_id)
                log_jsonl(log_path, {"level": "info", "stage": "skip", "reason": "no_public_item_details", "nen_url_id": nen_url_id})
                continue
            item_rows = [row for row in item_rows if is_medical_item_row(tender, row)]
            if not item_rows:
                logging.debug("Skipping %s because public item rows were not medical/healthcare items", nen_url_id)
                log_jsonl(log_path, {"level": "info", "stage": "skip", "reason": "no_medical_item_details", "nen_url_id": nen_url_id})
                continue

            logging.debug("Fetching result/award page for %s", nen_url_id)
            result = parse_result_page(fetcher, canonical_result_url(nen_url_id), nen_url_id)

            # Contract signing date summary on tender row.
            contract_dates = [r.get("contract_signing_date", "") for r in result["contracts"] if r.get("contract_signing_date")]
            contract_dates_iso = [r.get("contract_signing_date_iso", "") for r in result["contracts"] if r.get("contract_signing_date_iso")]
            tender["contract_signing_dates"] = " | ".join(contract_dates)
            tender["contract_signing_dates_iso"] = " | ".join(contract_dates_iso)
            tender["awarded_date"] = tender.get("award_result_publication_date") or (contract_dates[0] if contract_dates else "")
            tender["awarded_date_iso"] = tender.get("award_result_publication_date_iso") or (contract_dates_iso[0] if contract_dates_iso else "")
            tender["selected_suppliers"] = " | ".join(r.get("supplier_name", "") for r in result["contracts"] if r.get("supplier_name"))
            tender["contracts_json"] = json.dumps(result["contracts"], ensure_ascii=False)
            tender["participants_json"] = json.dumps(result["participants"], ensure_ascii=False)
            tender["subject_items_json"] = json.dumps(item_rows, ensure_ascii=False)

            tenders.append(tender)
            publication_records.extend(row_with_context(r, tender) for r in parsed["publication_rows"])
            contracts.extend(row_with_context(r, tender) for r in result["contracts"])
            participants.extend(row_with_context(r, tender) for r in result["participants"])
            subject_items.extend(row_with_context(r, tender) for r in item_rows)
            documents.extend(row_with_context(r, tender) for r in tender_documents)
            documents.extend(row_with_context(r, tender) for r in result["documents"])
            logging.info("Accepted %s | contracts=%s | items=%s | awarded_date=%s", nen_url_id, len(result["contracts"]), len(item_rows), tender.get("awarded_date", ""))
            log_jsonl(log_path, {"level": "info", "stage": "accepted", "nen_url_id": nen_url_id, "name": tender.get("tender_name_cs"), "status": tender.get("status_cs"), "publication_date": tender.get("publication_date"), "contracts": len(result["contracts"]), "items": len(item_rows)})
            if args.progress_every and args.progress_every > 0 and idx % args.progress_every == 0:
                logging.info("Progress summary: checked=%s/%s accepted=%s contracts=%s subject_items=%s", idx, len(candidate_ids), len(tenders), len(contracts), len(subject_items))
            if args.max_tenders and args.max_tenders > 0 and len(tenders) >= args.max_tenders:
                logging.info("Reached accepted-tender cap (%s); stopping detail phase.", args.max_tenders)
                break
        except Exception as exc:  # noqa: BLE001
            logging.exception("Failed tender %s", nen_url_id)
            log_jsonl(log_path, {"level": "error", "stage": "detail", "nen_url_id": nen_url_id, "url": detail_url, "error": str(exc)})

    logging.info("Detail phase finished. Accepted %s medical/healthcare tenders with detail current status Awarded/Zadán", len(tenders))

    # Add translations after all rows are assembled; caches repeated values.
    logging.info("Translation/export phase started.")
    add_translations(tenders, TRANSLATE_COLUMNS_TENDER, translator)
    add_translations(subject_items, TRANSLATE_COLUMNS_ITEM, translator)
    add_translations(publication_records, TRANSLATE_COLUMNS_PUBLICATION, translator)
    add_translations(documents, TRANSLATE_COLUMNS_DOCUMENT, translator)
    translator.save()
    logging.info("TRANSLATION cache saved: %s", output_dir / "translation_cache.json")

    # Build ONE flat table for ONE Excel sheet. This is the main requested output.
    all_columns_rows = build_all_columns_rows(tenders, contracts, participants, publication_records, subject_items, documents)
    logging.info("Built raw single-sheet table with %s rows and %s accepted tenders", len(all_columns_rows), len(tenders))
    final_rows = project_requested_item_columns(all_columns_rows)
    logging.info("Projected to requested one-sheet columns: %s rows", len(final_rows))

    excel_path = output_dir / args.all_columns_filename
    if args.write_csv:
        logging.info("Writing item_details_only.csv with %s rows", len(final_rows))
        write_csv(output_dir / "item_details_only.csv", final_rows)

    if not args.no_xlsx:
        logging.info("Writing ONE Excel workbook with ONE sheet and requested columns only: %s", excel_path)
        write_excel(excel_path, {"Item_Details": final_rows})

    if args.write_detail_sheets:
        audit_sheets = {
            "tenders": tenders,
            "contracts": contracts,
            "participants": participants,
            "subject_items": subject_items,
            "publication_records": publication_records,
            "documents": documents,
        }
        audit_path = output_dir / "czechia_nen_awarded_healthcare_detail_sheets_audit.xlsx"
        logging.info("Writing optional audit workbook with detail sheets: %s", audit_path)
        write_excel(audit_path, audit_sheets)

    summary = {
        "accepted_tenders": len(tenders),
        "raw_all_columns_rows": len(all_columns_rows),
        "item_detail_rows_exported": len(final_rows),
        "contracts": len(contracts),
        "participants": len(participants),
        "subject_items": len(subject_items),
        "publication_records": len(publication_records),
        "documents": len(documents),
        "excel_file": str(excel_path.resolve()) if not args.no_xlsx else "",
        "start_date": args.start_date,
        "end_date": args.end_date,
        "output_dir": str(output_dir.resolve()),
        "debug_log": str(debug_log_path.resolve()),
    }
    summary_path = output_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    logging.info("WROTE %s", summary_path)
    logging.info("FINISHED accepted_tenders=%s raw_rows=%s exported_item_rows=%s contracts=%s subject_items=%s documents=%s", len(tenders), len(all_columns_rows), len(final_rows), len(contracts), len(subject_items), len(documents))
    log_jsonl(log_path, {"level": "info", "stage": "finished", **summary})
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
