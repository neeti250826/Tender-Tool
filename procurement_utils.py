from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from bs4 import BeautifulSoup

FIELDNAMES = [
    "source",
    "country",
    "country_code",
    "publication_date",
    "closing_date",
    "title",
    "title_english",
    "description",
    "description_english",
    "buyer",
    "buyer_english",
    "classification",
    "classification_english",
    "status",
    "status_english",
    "currency",
    "amount",
    "awarding_agency_name",
    "awarding_agency_name_english",
    "supplier_name",
    "supplier_name_english",
    "awarded_date",
    "awarded_value_detail",
    "contract_period",
    "contract_period_english",
    "item_no",
    "item_description",
    "item_description_english",
    "item_uom",
    "item_quantity",
    "item_unit_price",
    "item_awarded_value",
    "notice_id",
    "notice_url",
    "query_text",
    "query_text_english",
    "scraped_at_utc",
    "dedup_key",
]

DEFAULT_MEDICAL_KEYWORDS = [
    "medical",
    "medicine",
    "medic",
    "pharma",
    "pharmaceutical",
    "pharmaceuticals",
    "drug",
    "drugs",
    "dosage",
    "dose",
    "hospital",
    "health",
    "healthcare",
    "clinic",
    "clinical",
    "lab",
    "laboratory",
    "laboratories",
    "diagnostic",
    "diagnostics",
    "ivd",
    "in vitro diagnostic",
    "test kit",
    "test kits",
    "kit",
    "kits",
    "device",
    "devices",
    "medical device",
    "medical devices",
    "equipment",
    "medical equipment",
    "hospital equipment",
    "consumable",
    "consumables",
    "medical consumable",
    "medical consumables",
    "medical supplies",
    "medical item",
    "medical items",
    "medical store",
    "medical store items",
    "hospital supplies",
    "supply of medicines",
    "drug supply",
    "medicine supply",
    "injectable",
    "injectables",
    "injection",
    "injections",
    "iv",
    "ivd reagents",
    "iv solution",
    "iv solutions",
    "disposable",
    "disposables",
    "suture",
    "sutures",
    "dressing",
    "dressings",
    "bandage",
    "bandages",
    "gauze",
    "cotton",
    "sanitizer",
    "sanitizers",
    "antiseptic",
    "antiseptics",
    "cannula",
    "cannulas",
    "infusion set",
    "infusion sets",
    "blood collection",
    "vacutainer",
    "vacutainers",
    "surgical",
    "surgery",
    "surgical disposable",
    "surgical disposables",
    "implant",
    "implants",
    "icu",
    "ventilator",
    "ventilators",
    "scanner",
    "ultrasound",
    "radiology",
    "radiography",
    "x-ray",
    "ct scan",
    "tomography",
    "mri",
    "mammography",
    "ecg",
    "ekg",
    "eeg",
    "dialyzer",
    "dialyzers",
    "nebulizer",
    "nebulizers",
    "defibrillator",
    "defibrillators",
    "pacemaker",
    "pacemakers",
    "stretcher",
    "stretchers",
    "wheelchair",
    "wheelchairs",
    "hospital bed",
    "hospital beds",
    "bedside monitor",
    "patient monitor",
    "patient monitors",
    "hematology analyzer",
    "haematology analyser",
    "biochemistry analyzer",
    "biochemistry analyser",
    "chemistry analyzer",
    "chemistry analyser",
    "microscope",
    "microscopes",
    "centrifuge",
    "centrifuges",
    "autoclave",
    "autoclaves",
    "incubator",
    "incubators",
    "sterilizer",
    "sterilizers",
    "sterilization",
    "ophthalmic",
    "ophthalmology",
    "dental",
    "dentistry",
    "dental material",
    "dental materials",
    "dental equipment",
    "dental supplies",
    "reagent",
    "reagents",
    "chemical",
    "chemicals",
    "glassware",
    "reference standard",
    "reference standards",
    "usp standard",
    "usp standards",
    "crm",
    "crms",
    "column",
    "columns",
    "catheter",
    "catheters",
    "guidewire",
    "guidewires",
    "dialysis",
    "hemodialysis",
    "haemodialysis",
    "peritoneal dialysis",
    "blood bank",
    "blood bag",
    "blood bags",
    "transfusion",
    "cancer",
    "oncology",
    "hematology",
    "haematology",
    "pathology",
    "histopathology",
    "microbiology",
    "virology",
    "serology",
    "immunology",
    "biochemistry",
    "first aid",
    "first aid kit",
    "first aid kits",
    "medical first aid kit",
    "medical first aid kits",
    "syringe",
    "syringes",
    "glove",
    "gloves",
    "mask",
    "masks",
    "pcr",
    "pcr kit",
    "pcr kits",
    "lab kit",
    "lab kits",
    "analyzer",
    "analyser",
    "monitor",
    "monitors",
    "infusion",
    "biomedical",
    "biomed",
    "ivf",
    "icu consumables",
    "ward supplies",
    "clinical consumables",
    "surgical consumables",
    "sterile consumables",
    "diagnostic consumables",
    "laboratory consumables",
    "lab consumables",
    "hospital consumables",
    "medical gas",
    "anaesthesia machine",
    "anesthesia machine",
    "endotracheal",
    "laryngoscope",
    "suction machine",
    "bp apparatus",
    "blood pressure",
    "stethoscope",
    "thermometer",
    "glucometer",
    "otoscope",
    "ultrasound gel",
    "iv fluid",
    "iv fluids",
    "dialysis solution",
    "dialysis solutions",
    "haemosol",
    "prismaflex",
    "ivd kit",
    "ivd kits",
    "rapid test",
    "rapid tests",
    "elisa",
    "elisa kit",
    "elisa kits",
    "pcr reagent",
    "pcr reagents",
    "oxygen",
    "oxygen cylinder",
    "oxygen concentrator",
    "rehabilitation",
    "physiotherapy",
    "orthopedic",
    "orthopaedic",
    "prosthesis",
    "prostheses",
    "stent",
    "stents",
    "catheterization",
    "endoscopy",
    "bronchoscopy",
    "colonoscopy",
    "anaesthesia",
    "anesthesia",
    "sterility",
    "antibiotic",
    "vaccine",
    "vaccines",
    "biological",
    "biologicals",
    "therapeutic",
    "therapeutics",
    "antiviral",
    "antivirals",
    "antifungal",
    "antifungals",
    "antimalarial",
    "antimalarials",
    "insulin",
    "iv cannula",
    "iv cannulas",
    "needle",
    "needles",
    "urine bag",
    "urine bags",
    "specimen",
    "specimens",
    "sample collection",
    "swab",
    "swabs",
    "consumable items",
    "diagnostic kits",
    "ministry of health",
    "health department",
    "polyclinic",
    "dispensary",
    "ward",
    "emergency room",
    "trauma",
    "nicu",
    "picu",
]

MONTH_MAP = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


def clean_text(value: Optional[str]) -> str:
    if value is None:
        return ""
    raw = str(value)
    if "<" in raw and ">" in raw:
        raw = BeautifulSoup(raw, "html.parser").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", raw).strip()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def stable_key(*parts: str) -> str:
    joined = "|".join(clean_text(part) for part in parts)
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()


def parse_date_to_iso(value: str) -> str:
    text = clean_text(value)
    if not text:
        return ""
    for fmt in (
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%m/%d/%Y",
        "%B %d, %Y",
        "%b %d, %Y",
        "%d %B %Y",
        "%d %b %Y",
    ):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            pass
    iso_match = re.search(r"\d{4}-\d{2}-\d{2}", text)
    if iso_match:
        return iso_match.group(0)
    english_match = re.search(r"([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})", text)
    if english_match:
        month = MONTH_MAP.get(english_match.group(1).lower())
        if month:
            return date(int(english_match.group(3)), month, int(english_match.group(2))).isoformat()
    return ""


def in_date_window(iso_value: str, date_from: str, date_to: str) -> bool:
    value = parse_date_to_iso(iso_value)
    if not value:
        return False
    start = parse_date_to_iso(date_from)
    end = parse_date_to_iso(date_to)
    if start and value < start:
        return False
    if end and value > end:
        return False
    return True


def split_amount_and_currency(value: str, default_currency: str = "") -> Tuple[str, str]:
    text = clean_text(value)
    if not text:
        return "", default_currency
    currency = default_currency
    upper_text = text.upper()
    if "KWD" in upper_text or "KD" in upper_text:
        currency = "KWD"
    elif "PKR" in upper_text or "RS." in upper_text or upper_text.startswith("RS "):
        currency = "PKR"
    elif "AED" in upper_text:
        currency = "AED"
    elif "USD" in upper_text or "$" in text:
        currency = "USD"
    amount_match = re.search(r"-?\d[\d,]*(?:\.\d+)?", text)
    numeric = amount_match.group(0).replace(",", "") if amount_match else ""
    return numeric, currency


def _word_to_int(value: str) -> int:
    mapping = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
        "eleven": 11,
        "twelve": 12,
    }
    text = clean_text(value).lower()
    if text.isdigit():
        return int(text)
    return mapping.get(text, 0)


def _format_duration_from_days(days_inclusive: int) -> str:
    if days_inclusive <= 0:
        return ""
    if days_inclusive % 365 == 0:
        years = days_inclusive // 365
        return f"{years} year" if years == 1 else f"{years} years"
    if days_inclusive % 30 == 0:
        months = days_inclusive // 30
        return f"{months} month" if months == 1 else f"{months} months"
    return f"{days_inclusive} days"


def _format_duration(count: int, unit: str) -> str:
    singular_unit = unit[:-1] if unit.endswith("s") else unit
    plural_unit = singular_unit if count == 1 else f"{singular_unit}s"
    return f"{count} {plural_unit}"


def _normalize_contract_period(value: str, allow_verbatim: bool) -> str:
    text = clean_text(value)
    if not text:
        return ""

    fy_match = re.search(r"\bFY\s*(\d{4})\s*[-/]\s*(\d{2,4})\b", text, flags=re.IGNORECASE)
    if fy_match:
        return "1 year"

    explicit_duration = re.search(
        r"\b(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|\d+)\s+"
        r"((?:working\s+)?day|(?:working\s+)?days|month|months|year|years)\b",
        text,
        flags=re.IGNORECASE,
    )
    if explicit_duration:
        count = _word_to_int(explicit_duration.group(1))
        unit = explicit_duration.group(2).lower()
        if count:
            if unit.startswith("working "):
                normalized_unit = "working day" if "day" in unit and count == 1 else "working days"
                return f"{count} {normalized_unit}"
            return _format_duration(count, unit)

    hyphenated_duration = re.search(
        r"\b(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|\d+)[-\s]+"
        r"(day|days|month|months|year|years)\b",
        text,
        flags=re.IGNORECASE,
    )
    if hyphenated_duration:
        count = _word_to_int(hyphenated_duration.group(1))
        unit = hyphenated_duration.group(2).lower()
        if count:
            return _format_duration(count, unit)

    range_match = re.search(
        r"(?:(?:from)\s+)?(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4}|[A-Za-z]{3,9}\s+\d{1,2},\s+\d{4})\s+"
        r"(?:to|until|through|-)\s+"
        r"(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4}|[A-Za-z]{3,9}\s+\d{1,2},\s+\d{4})",
        text,
        flags=re.IGNORECASE,
    )
    if range_match:
        start_iso = parse_date_to_iso(range_match.group(1))
        end_iso = parse_date_to_iso(range_match.group(2))
        if start_iso and end_iso:
            start_date = datetime.strptime(start_iso, "%Y-%m-%d").date()
            end_date = datetime.strptime(end_iso, "%Y-%m-%d").date()
            if end_date >= start_date:
                end_plus_one = end_date + timedelta(days=1)
                whole_months = (end_plus_one.year - start_date.year) * 12 + (end_plus_one.month - start_date.month)
                if whole_months > 0 and end_plus_one.day == start_date.day:
                    if whole_months % 12 == 0:
                        years = whole_months // 12
                        return f"{years} year" if years == 1 else f"{years} years"
                    return f"{whole_months} months"
                return _format_duration_from_days((end_date - start_date).days + 1)

    day_range = re.search(r"\b(\d+)\s*-\s*(\d+)\s*days\b", text, flags=re.IGNORECASE)
    if day_range:
        return f"{day_range.group(1)}-{day_range.group(2)} days"

    return "" if not allow_verbatim else ""


def normalize_contract_period(value: str) -> str:
    return _normalize_contract_period(value, allow_verbatim=False)


def derive_contract_period(row: Dict[str, str]) -> str:
    direct_value = normalize_contract_period(row.get("contract_period", ""))
    if direct_value:
        return direct_value
    for fallback_key in ("description", "title", "awarded_value_detail", "query_text"):
        derived = _normalize_contract_period(row.get(fallback_key, ""), allow_verbatim=False)
        if derived:
            return derived
    return ""


def normalize_keyword_list(raw_keywords: str) -> List[str]:
    parts = [clean_text(part).lower() for part in raw_keywords.split(",")]
    return [part for part in parts if part]


def matched_keywords(text: str, keywords: Sequence[str]) -> List[str]:
    lowered = clean_text(text).lower()
    matches: List[str] = []
    for keyword in keywords:
        candidate = clean_text(keyword).lower()
        if not candidate:
            continue
        if len(candidate) <= 3:
            pattern = rf"(?<![a-z0-9]){re.escape(candidate)}(?![a-z0-9])"
            if re.search(pattern, lowered):
                matches.append(candidate)
            continue
        if candidate in lowered:
            matches.append(candidate)
    return matches


def looks_english(value: str) -> bool:
    text = clean_text(value)
    if not text:
        return True
    letters = re.findall(r"[A-Za-z]", text)
    non_ascii_letters = re.findall(r"[^\x00-\x7F]", text)
    return bool(letters) and len(non_ascii_letters) <= max(2, len(text) // 20)


@dataclass
class OptionalTranslator:
    enabled: bool = True
    _translator: object | None = None
    _cache: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.enabled:
            return
        try:
            from deep_translator import GoogleTranslator
        except ImportError:
            self.enabled = False
            return
        self._translator = GoogleTranslator(source="auto", target="en")

    def translate(self, value: str) -> str:
        text = clean_text(value)
        if not text:
            return ""
        if looks_english(text) or not self.enabled or self._translator is None:
            return text
        if text in self._cache:
            return self._cache[text]
        try:
            translated = clean_text(self._translator.translate(text))
        except Exception:
            translated = text
        self._cache[text] = translated or text
        return self._cache[text]


def add_translation_columns(row: Dict[str, str], translator: OptionalTranslator) -> Dict[str, str]:
    translated = dict(row)
    translated["contract_period"] = derive_contract_period(row)

    def translated_or_existing(existing_key: str, source_key: str) -> str:
        existing_value = clean_text(row.get(existing_key, ""))
        if existing_value:
            return existing_value
        return translator.translate(row.get(source_key, ""))

    translated["title_english"] = translated_or_existing("title_english", "title")
    translated["description_english"] = translated_or_existing("description_english", "description")
    translated["buyer_english"] = translated_or_existing("buyer_english", "buyer")
    translated["classification_english"] = translated_or_existing("classification_english", "classification")
    translated["status_english"] = translated_or_existing("status_english", "status")
    translated["awarding_agency_name_english"] = translated_or_existing("awarding_agency_name_english", "awarding_agency_name")
    translated["supplier_name_english"] = translated_or_existing("supplier_name_english", "supplier_name")
    translated["contract_period_english"] = translator.translate(translated.get("contract_period", ""))
    translated["item_description_english"] = translated_or_existing("item_description_english", "item_description")
    translated["query_text_english"] = translated_or_existing("query_text_english", "query_text")
    return translated


def ensure_fieldnames(row: Dict[str, str]) -> Dict[str, str]:
    normalized = dict(row)
    normalized["contract_period"] = derive_contract_period(row) or clean_text(row.get("contract_period", ""))
    if (
        not clean_text(normalized.get("currency", ""))
        and clean_text(normalized.get("country_code", "")) == "PK"
        and (clean_text(normalized.get("amount", "")) or clean_text(normalized.get("awarded_value_detail", "")))
    ):
        normalized["currency"] = "PKR"
    if not clean_text(normalized.get("amount", "")):
        amount, inferred_currency = split_amount_and_currency(
            normalized.get("awarded_value_detail", ""),
            default_currency=clean_text(normalized.get("currency", "")),
        )
        if amount:
            normalized["amount"] = amount
        if inferred_currency and not clean_text(normalized.get("currency", "")):
            normalized["currency"] = inferred_currency
    if not clean_text(normalized.get("awarded_value_detail", "")):
        amount = clean_text(normalized.get("amount", ""))
        currency = clean_text(normalized.get("currency", ""))
        status = clean_text(normalized.get("status", "")).lower()
        if amount and status in {"awarded", "loi issued", "contracted", "completed"}:
            normalized["awarded_value_detail"] = f"{currency} {amount}".strip()
    return {field: clean_text(normalized.get(field, "")) for field in FIELDNAMES}


def serialize_rows(rows: Iterable[Dict[str, str]], output_jsonl: str, output_csv: str) -> None:
    jsonl_path = Path(output_jsonl)
    csv_path = Path(output_csv)
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    materialized = [ensure_fieldnames(row) for row in rows]
    with jsonl_path.open("w", encoding="utf-8") as handle:
        for row in materialized:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(materialized)
