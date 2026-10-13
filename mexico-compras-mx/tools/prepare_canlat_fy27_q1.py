"""Prepare the CANLAT FY27 Q1 tender workbook from the formatted extract.

The script keeps the source workbook unchanged. It reuses translations from the
previous CANLAT tender file, stores machine-translation progress in SQLite so a
failed run can resume, and writes a separate FY27 Q1 workbook.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import logging
import os
import random
import re
import shutil
import sqlite3
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

import requests
from openpyxl import load_workbook


WINDOW_START = date(2026, 5, 1)
WINDOW_END = date(2026, 7, 31)
QUARTER_LABEL = "Q1 FY27"

SOURCE_DESCRIPTION_COL = 9  # I: Detailed description (ESP)
ENGLISH_DESCRIPTION_COL = 10  # J: Detailed description (ENG)
RELEVANCE_COL = 11  # K: Irrelevant/Relevant
UNIT_EN_COL = 12  # L: Unit of measure - EN
START_DATE_COL = 26  # Z: Start Date
END_DATE_COL = 27  # AA: End Date
QUARTER_COL = 38  # AL: When was this tender found?
RELEVANT_MONTHS_COL = 39  # AM: No. of relevant months


def normalized_key(value: object) -> str:
    """Normalize values for robust matching without altering workbook text."""
    return re.sub(r"\s+", " ", str(value or "").strip()).upper()


def as_date(value: object) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = value.strip()
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                pass
    return None


def iter_rows(ws) -> Iterator[Tuple[object, ...]]:
    """Yield used rows while supporting source workbooks without dimensions."""
    yield from ws.iter_rows(min_row=2, values_only=True)


def collect_source_descriptions(source_path: Path) -> Dict[str, str]:
    workbook = load_workbook(source_path, read_only=True, data_only=False)
    worksheet = workbook.active
    descriptions: Dict[str, str] = {}
    for row in iter_rows(worksheet):
        if len(row) < SOURCE_DESCRIPTION_COL:
            continue
        value = row[SOURCE_DESCRIPTION_COL - 1]
        key = normalized_key(value)
        if key:
            descriptions.setdefault(key, str(value).strip())
    workbook.close()
    return descriptions


def collect_reference_translations(reference_path: Path) -> Tuple[Dict[str, str], Dict[str, str]]:
    workbook = load_workbook(reference_path, read_only=True, data_only=False)
    worksheet = workbook["Tenders"]
    translations: Dict[str, str] = {}
    units: Dict[str, str] = {}

    for row in iter_rows(worksheet):
        if len(row) < UNIT_EN_COL:
            continue
        key = normalized_key(row[SOURCE_DESCRIPTION_COL - 1])
        if not key:
            continue
        english = row[ENGLISH_DESCRIPTION_COL - 1]
        unit = row[UNIT_EN_COL - 1]
        if english not in (None, ""):
            translations.setdefault(key, str(english).strip())
        if unit not in (None, ""):
            units.setdefault(key, str(unit).strip())

    workbook.close()
    return translations, units


def create_cache(cache_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(cache_path)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS translations (
            description_key TEXT PRIMARY KEY,
            translation TEXT NOT NULL,
            translation_source TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    return connection


def read_cache(connection: sqlite3.Connection, keys: Iterable[str]) -> Dict[str, str]:
    requested = list(keys)
    found: Dict[str, str] = {}
    chunk_size = 900
    for offset in range(0, len(requested), chunk_size):
        chunk = requested[offset : offset + chunk_size]
        placeholders = ",".join("?" for _ in chunk)
        query = f"SELECT description_key, translation FROM translations WHERE description_key IN ({placeholders})"
        found.update(dict(connection.execute(query, chunk).fetchall()))
    return found


def write_cache(connection: sqlite3.Connection, values: Sequence[Tuple[str, str, str]]) -> None:
    if not values:
        return
    connection.executemany(
        """
        INSERT INTO translations (description_key, translation, translation_source, updated_at)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(description_key) DO UPDATE SET
            translation = excluded.translation,
            translation_source = excluded.translation_source,
            updated_at = excluded.updated_at
        """,
        values,
    )
    connection.commit()


def translate_payload(payload: str) -> str:
    response = requests.get(
        "https://translate.googleapis.com/translate_a/single",
        params={"client": "gtx", "sl": "es", "tl": "en", "dt": "t", "q": payload},
        timeout=45,
    )
    response.raise_for_status()
    body = response.json()
    return "".join(part[0] for part in body[0] if part and part[0])


def translate_with_retry(payload: str, attempts: int = 6) -> str:
    last_error: Optional[Exception] = None
    for attempt in range(1, attempts + 1):
        try:
            return translate_payload(payload)
        except Exception as error:  # Network/API failures are retried and logged by the caller.
            last_error = error
            if attempt < attempts:
                time.sleep(min(30, (2 ** (attempt - 1)) + random.random()))
    raise RuntimeError(f"translation failed after {attempts} attempts: {last_error}")


def split_long_text(text: str, max_chars: int) -> List[str]:
    if len(text) <= max_chars:
        return [text]

    pieces = re.split(r"(?<=[.;:])\s+|\n+", text)
    chunks: List[str] = []
    current = ""
    for piece in pieces:
        if not piece:
            continue
        if len(piece) > max_chars:
            words = piece.split()
            while words:
                segment = ""
                while words and len(segment) + len(words[0]) + 1 <= max_chars:
                    segment = f"{segment} {words.pop(0)}".strip()
                if not segment:
                    segment = words.pop(0)[:max_chars]
                if current:
                    chunks.append(current)
                    current = ""
                chunks.append(segment)
            continue
        candidate = f"{current} {piece}".strip()
        if current and len(candidate) > max_chars:
            chunks.append(current)
            current = piece
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def translate_one(key: str, text: str, max_chars: int) -> Tuple[str, str]:
    chunks = split_long_text(text, max_chars)
    if len(chunks) == 1:
        return key, translate_with_retry(chunks[0]).strip()
    return key, " ".join(translate_with_retry(chunk).strip() for chunk in chunks).strip()


def translate_batch(
    batch_number: int,
    entries: Sequence[Tuple[str, str]],
    max_chars: int,
) -> List[Tuple[str, str]]:
    if len(entries) == 1:
        return [translate_one(entries[0][0], entries[0][1], max_chars)]

    sentinels = [f"<<<__CANLAT_SEGMENT_{batch_number}_{index}__>>>" for index in range(len(entries) - 1)]
    payload_parts: List[str] = []
    for index, (_, text) in enumerate(entries):
        payload_parts.append(text)
        if index < len(sentinels):
            payload_parts.append(sentinels[index])
    payload = "\n".join(payload_parts)

    translated = translate_with_retry(payload)
    pattern = r"\s*(?:" + "|".join(re.escape(sentinel) for sentinel in sentinels) + r")\s*"
    translated_parts = re.split(pattern, translated)
    if len(translated_parts) != len(entries) or any(not item.strip() for item in translated_parts):
        logging.warning("Batch %s delimiter parse failed; retrying %s descriptions individually.", batch_number, len(entries))
        return [translate_one(key, text, max_chars) for key, text in entries]
    return [(key, english.strip()) for (key, _), english in zip(entries, translated_parts)]


def create_batches(entries: Iterable[Tuple[str, str]], max_chars: int) -> List[List[Tuple[str, str]]]:
    batches: List[List[Tuple[str, str]]] = []
    current: List[Tuple[str, str]] = []
    current_chars = 0
    delimiter_reserve = 64
    for key, text in entries:
        if len(text) > max_chars:
            if current:
                batches.append(current)
                current = []
                current_chars = 0
            batches.append([(key, text)])
            continue
        projected = current_chars + len(text) + delimiter_reserve
        if current and projected > max_chars:
            batches.append(current)
            current = []
            current_chars = 0
        current.append((key, text))
        current_chars += len(text) + delimiter_reserve
    if current:
        batches.append(current)
    return batches


def translate_missing(
    connection: sqlite3.Connection,
    descriptions: Dict[str, str],
    workers: int,
    max_chars: int,
) -> Tuple[int, int]:
    cached = read_cache(connection, descriptions)
    missing = [(key, text) for key, text in descriptions.items() if key not in cached]
    if not missing:
        logging.info("Translation cache already covers every source description.")
        return 0, 0

    batches = create_batches(missing, max_chars)
    logging.info(
        "Machine-translating %s unmatched descriptions in %s batches with %s workers.",
        len(missing),
        len(batches),
        workers,
    )
    translated = 0
    failures = 0
    completed_batches = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(translate_batch, batch_number, batch, max_chars): (batch_number, batch)
            for batch_number, batch in enumerate(batches, start=1)
        }
        for future in concurrent.futures.as_completed(futures):
            batch_number, batch = futures[future]
            completed_batches += 1
            try:
                results = future.result()
                write_cache(connection, [(key, english, "google") for key, english in results if english])
                translated += len(results)
            except Exception as error:
                failures += len(batch)
                logging.error("Batch %s failed for %s descriptions: %s", batch_number, len(batch), error)
            if completed_batches % 25 == 0 or completed_batches == len(batches):
                logging.info(
                    "Translation progress: %s/%s batches | %s descriptions stored | %s descriptions failed.",
                    completed_batches,
                    len(batches),
                    translated,
                    failures,
                )
    return translated, failures


def relevant_month_formula(row: int) -> str:
    # Preserve the existing contract-month methodology, with the FY27 Q1 date window.
    return (
        f'=IFERROR(MAX(0,DATEDIF(MAX(Z{row},DATE(2026,5,1)),'
        f'MIN(AA{row},DATE(2026,7,31)),"m")+1),0)'
    )


def clean_translation(text: str) -> str:
    """Fix the small set of repeated, unambiguous machine-translation artifacts."""
    replacements = (
        (r"\bPONELESS\b", "PITTED"),
        (r"\bANESTHESIC\b", "ANESTHETIC"),
        (r"\bSANDAPES\b", "SANDPAPER"),
        (r"\bDIELECTRIC STIFFNESS\b", "DIELECTRIC STRENGTH"),
        (r"\bDISINTEGRATE GREASES, DIRT AND DUST\b", "DISSOLVES GREASE, GRIME, AND DUST"),
        (r"\bCHLORINE FLUORO CARBONS\b", "CHLOROFLUOROCARBONS"),
    )
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text)
    return text


def write_workbook(
    source_path: Path,
    output_path: Path,
    translations: Dict[str, str],
    units: Dict[str, str],
) -> Dict[str, int]:
    temporary_path = output_path.with_suffix(".in_progress.xlsx")
    shutil.copy2(source_path, temporary_path)
    workbook = load_workbook(temporary_path, data_only=False)
    worksheet = workbook.active

    worksheet["AI1"] = "Value for sizing period \n(May - July 2026)"
    worksheet["AJ1"] = "Volume for sizing period \n(May - July 2026)"

    stats = {
        "rows": 0,
        "english_filled": 0,
        "english_missing": 0,
        "units_filled": 0,
        "in_time_frame": 0,
        "out_of_time_frame": 0,
        "invalid_dates": 0,
    }
    for row in range(2, worksheet.max_row + 1):
        stats["rows"] += 1
        description_key = normalized_key(worksheet.cell(row, SOURCE_DESCRIPTION_COL).value)
        translation = translations.get(description_key)
        if translation:
            worksheet.cell(row, ENGLISH_DESCRIPTION_COL).value = clean_translation(translation)
            stats["english_filled"] += 1
        else:
            worksheet.cell(row, ENGLISH_DESCRIPTION_COL).value = None
            stats["english_missing"] += 1

        unit = units.get(description_key)
        if unit:
            worksheet.cell(row, UNIT_EN_COL).value = unit
            stats["units_filled"] += 1

        start_date = as_date(worksheet.cell(row, START_DATE_COL).value)
        end_date = as_date(worksheet.cell(row, END_DATE_COL).value)
        if start_date is None or end_date is None:
            stats["invalid_dates"] += 1
        elif end_date < WINDOW_START or start_date > WINDOW_END:
            worksheet.cell(row, RELEVANCE_COL).value = "Out of time frame"
            stats["out_of_time_frame"] += 1
        else:
            stats["in_time_frame"] += 1

        worksheet.cell(row, QUARTER_COL).value = QUARTER_LABEL
        worksheet.cell(row, RELEVANT_MONTHS_COL).value = relevant_month_formula(row)

    try:
        workbook.calculation.fullCalcOnLoad = True
        workbook.calculation.forceFullCalc = True
        workbook.calculation.calcMode = "auto"
    except AttributeError:
        pass
    workbook.save(temporary_path)
    workbook.close()
    os.replace(temporary_path, output_path)
    return stats


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path, help="Formatted CANLAT source workbook.")
    parser.add_argument("--reference", required=True, type=Path, help="Prior CANLAT tender workbook with reviewed translations.")
    parser.add_argument("--output", required=True, type=Path, help="FY27 Q1 workbook to create.")
    parser.add_argument("--cache", type=Path, help="SQLite cache for resumable translations.")
    parser.add_argument("--log", type=Path, help="Log file path.")
    parser.add_argument("--workers", type=int, default=6, help="Concurrent translation requests (default: 6).")
    parser.add_argument("--request-chars", type=int, default=3600, help="Maximum source characters per translation request.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    args.source = args.source.resolve()
    args.reference = args.reference.resolve()
    args.output = args.output.resolve()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    cache_path = (args.cache or args.output.with_suffix(".translation_cache.sqlite3")).resolve()
    log_path = (args.log or args.output.with_suffix(".log")).resolve()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(log_path, encoding="utf-8"), logging.StreamHandler(sys.stdout)],
    )

    logging.info("Collecting unique Spanish descriptions from %s", args.source)
    source_descriptions = collect_source_descriptions(args.source)
    logging.info("Found %s unique source descriptions.", len(source_descriptions))

    logging.info("Reading verified translations from %s", args.reference)
    reference_translations, reference_units = collect_reference_translations(args.reference)
    reusable_translations = {
        key: english for key, english in reference_translations.items() if key in source_descriptions
    }
    reusable_units = {key: unit for key, unit in reference_units.items() if key in source_descriptions}
    logging.info(
        "Matched %s verified English descriptions and %s verified English unit labels from the reference workbook.",
        len(reusable_translations),
        len(reusable_units),
    )

    connection = create_cache(cache_path)
    write_cache(connection, [(key, english, "reference") for key, english in reusable_translations.items()])
    _, failures = translate_missing(connection, source_descriptions, max(1, args.workers), args.request_chars)
    translations = read_cache(connection, source_descriptions)
    connection.close()
    logging.info(
        "Translation coverage before workbook generation: %s/%s unique descriptions (%s unresolved).",
        len(translations),
        len(source_descriptions),
        len(source_descriptions) - len(translations),
    )

    logging.info("Writing FY27 Q1 workbook to %s", args.output)
    stats = write_workbook(args.source, args.output, translations, reusable_units)
    logging.info("Workbook complete: %s", stats)
    if failures or stats["english_missing"]:
        logging.warning("The workbook was written with %s unresolved English descriptions.", stats["english_missing"])
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
