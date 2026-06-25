import csv
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple

from deep_translator import GoogleTranslator


FIELDNAMES: List[str] = [
    "source",
    "country",
    "country_code",
    "publication_date",
    "closing_date",
    "title",
    "description",
    "buyer",
    "classification",
    "status",
    "currency",
    "amount",
    "awarding_agency_name",
    "supplier_name",
    "awarded_date",
    "awarded_value_detail",
    "contract_period",
    "item_no",
    "item_description",
    "item_uom",
    "item_quantity",
    "item_unit_price",
    "item_awarded_value",
    "notice_id",
    "notice_url",
    "query_text",
    "scraped_at_utc",
    "dedup_key",
]

TRANSLATED_FIELDS: List[str] = [
    "title",
    "description",
    "buyer",
    "classification",
    "status",
    "awarding_agency_name",
    "supplier_name",
    "contract_period",
    "item_description",
]

CSV_FIELDNAMES: List[str] = []
for field in FIELDNAMES:
    CSV_FIELDNAMES.append(field)
    if field in TRANSLATED_FIELDS:
        CSV_FIELDNAMES.append(f"{field}_en")


REQUIRED_NON_EMPTY_FIELDS = [
    "source",
    "country",
    "country_code",
    "title",
    "notice_url",
    "query_text",
    "scraped_at_utc",
    "dedup_key",
]


def row_to_dict(row: Any) -> Dict[str, Any]:
    if isinstance(row, dict):
        return row
    return asdict(row)


def write_jsonl(path: str, rows: Sequence[Any]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row_to_dict(row), ensure_ascii=False) + "\n")


def append_jsonl(path: str, rows: Sequence[Any]) -> None:
    with open(path, "a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row_to_dict(row), ensure_ascii=False) + "\n")


def write_csv(path: str, rows: Sequence[Any]) -> None:
    translation_cache: Dict[str, str] = {}
    translator = GoogleTranslator(source="auto", target="en")

    def translate_value(value: Any) -> Any:
        if value is None or value == "":
            return value
        if not isinstance(value, str):
            return value
        text = value.strip()
        if not text:
            return text
        if text in translation_cache:
            return translation_cache[text]
        if not contains_arabic(text):
            translation_cache[text] = text
            return text
        try:
            translated = translator.translate(text)
        except Exception:
            translated = text
        translation_cache[text] = translated
        return translated

    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            source_row = row_to_dict(row)
            normalized: Dict[str, Any] = {}
            for field in FIELDNAMES:
                normalized[field] = source_row.get(field)
                if field in TRANSLATED_FIELDS:
                    normalized[f"{field}_en"] = translate_value(source_row.get(field))
            writer.writerow(normalized)


def load_jsonl(path: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            rows.append(json.loads(stripped))
    return rows


def validate_rows(rows: Iterable[Dict[str, Any]]) -> Tuple[List[str], int]:
    errors: List[str] = []
    count = 0
    for index, row in enumerate(rows, start=1):
        count += 1
        missing_columns = [field for field in FIELDNAMES if field not in row]
        if missing_columns:
            errors.append(f"row {index}: missing columns: {', '.join(missing_columns)}")
        extra_columns = sorted(set(row.keys()) - set(FIELDNAMES))
        if extra_columns:
            errors.append(f"row {index}: unexpected columns: {', '.join(extra_columns)}")
        for field in REQUIRED_NON_EMPTY_FIELDS:
            value = row.get(field)
            if value is None or value == "":
                errors.append(f"row {index}: empty required field: {field}")
    if count == 0:
        errors.append("file contains no data rows")
    return errors, count


def validate_jsonl_file(path: str) -> Tuple[List[str], int]:
    return validate_rows(load_jsonl(path))


def ensure_parent_dir(path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)


def contains_arabic(text: str) -> bool:
    return any("\u0600" <= char <= "\u06FF" for char in text)
