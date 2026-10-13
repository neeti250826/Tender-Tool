"""Map CANLAT tender taxonomy fields from reviewed historical tender workbooks.

The mapper deliberately fills only evidence-backed values. It prefers exact
historical matches and uses conservative phrase evidence only when the
historical label is consistent. This keeps unclassified rows blank rather than
assigning an unsupported taxonomy.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

from openpyxl import load_workbook


LABEL_HEADERS = (
    "Sub OU",
    "Product Category",
    "Manufacturer Name",
    "Family Name",
)
LABEL_FIELD_NAMES = ("sub_ou", "product_category", "manufacturer_name", "family_name")
TOKEN_PATTERN = re.compile(r"[A-Z0-9]+", re.IGNORECASE)
STOP_WORDS = {
    "CON", "PARA", "DEL", "DE", "LA", "EL", "LOS", "LAS", "Y", "EN", "POR", "UN", "UNA",
    "THE", "AND", "FOR", "WITH", "FROM", "TO", "OF", "IN", "OR", "A", "AN", "TYPE", "USE",
    "PIEZA", "PIEZAS", "PZA", "PZAS", "CAJA", "PAQUETE", "PACK", "KIT", "SET", "BOX", "PCS",
    "ADULTO", "ADULT", "PACIENTE", "PATIENT", "PACIENTES", "PATIENTS", "NO", "SIN", "NON",
}
PLACEHOLDER_LABELS = {
    "", "GENERIC", "OTHER", "OTHERS", "UNCLEAR", "UNSPECIFIED", "NOT IDENTIFIED", "N A", "NA", "N/A",
}
IDENTIFIER_STOP_WORDS = {
    "AMERICAN", "APPLIED", "COMPANY", "CORPORATION", "CORP", "GENERAL", "GROUP", "HEALTH", "HEALTHCARE",
    "INC", "INTERNATIONAL", "LABORATORIES", "LIMITED", "LTD", "MEDICAL", "NORTH", "PRODUCTS", "SCIENTIFIC",
    "SOUTH", "TECHNOLOGIES", "TECHNOLOGY", "UNITED",
}
FAMILY_GENERIC_IDENTIFIERS = {
    "ACCESS", "ADULT", "BALLOON", "BLADE", "CANNULA", "CATHETER", "CATHETERS", "CIRCUIT", "CIRCUITS",
    "DIAMOND", "DISPOSABLE", "ELECTRODE", "ELECTRODES", "GENERIC", "GUIDEWIRE", "GUIDEWIRES", "MASK", "MASKS",
    "NEEDLE", "NEEDLES", "NEONATAL", "OTHER", "OTHERS", "PEDIATRIC", "PLATE", "PLATES", "PRECISE", "REINFORCED",
    "STANDARD", "TUBE", "TUBES", "UNCLEAR", "UNSPECIFIED",
}


@dataclass(frozen=True)
class TenderRecord:
    code: str
    spanish: str
    english: str
    labels: Tuple[str, str, str, str]


def normalized_header(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\n", " ").strip()).casefold()


def normalized_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).upper()


def token_text(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(character for character in text if not unicodedata.combining(character))
    return re.sub(r"\s+", " ", text).upper().strip()


def tokenize(value: object) -> List[str]:
    return [token for token in TOKEN_PATTERN.findall(token_text(value)) if len(token) >= 3 and token not in STOP_WORDS]


def ngrams(tokens: Sequence[str], minimum: int = 2, maximum: int = 4) -> Iterator[str]:
    seen = set()
    for width in range(minimum, maximum + 1):
        for index in range(len(tokens) - width + 1):
            phrase = " ".join(tokens[index : index + width])
            if phrase not in seen:
                seen.add(phrase)
                yield phrase


def is_placeholder_label(value: object) -> bool:
    return token_text(value) in PLACEHOLDER_LABELS


def raw_label_tokens(value: object) -> List[str]:
    return TOKEN_PATTERN.findall(token_text(value))


def manufacturer_identifier_forms(value: object) -> List[str]:
    """Return a direct, non-generic identifier written in a manufacturer label."""
    tokens = [
        token for token in raw_label_tokens(value)
        if len(token) >= 4 and token not in IDENTIFIER_STOP_WORDS
    ]
    if not tokens:
        return []
    # Multi-word labels require the full direct name. For single-word labels,
    # the term itself is sufficiently specific to use as an identifier.
    return [" ".join(tokens)]


def family_identifier_forms(value: object) -> List[str]:
    """Return a direct product-family name without reducing it to generic words."""
    tokens = [token for token in raw_label_tokens(value) if token not in IDENTIFIER_STOP_WORDS]
    if len(tokens) >= 2:
        return [" ".join(tokens)]
    if len(tokens) == 1 and len(tokens[0]) >= 5 and tokens[0] not in FAMILY_GENERIC_IDENTIFIERS:
        return tokens
    return []


def find_columns(worksheet) -> Dict[str, int]:
    header = next(worksheet.iter_rows(min_row=1, max_row=1, values_only=True))
    columns: Dict[str, int] = {}
    for index, value in enumerate(header):
        normalized = normalized_header(value)
        if normalized == "clave cucop+":
            columns["code"] = index
        elif normalized == "detailed description (esp)":
            columns["spanish"] = index
        elif normalized in {"detailed description (eng)", "english"}:
            columns["english"] = index
        elif normalized == "sub ou":
            columns["sub_ou"] = index
        elif normalized.startswith("product category"):
            columns["product_category"] = index
        elif normalized.startswith("manufacturer name"):
            columns["manufacturer_name"] = index
        elif normalized.startswith("family name"):
            columns["family_name"] = index
    required = {"code", "spanish", "english", *LABEL_FIELD_NAMES}
    missing = sorted(required - set(columns))
    if missing:
        raise ValueError(f"{worksheet.title} is missing required columns: {', '.join(missing)}")
    return columns


def iter_records(path: Path, sheet_name: Optional[str] = "Tenders") -> Iterator[TenderRecord]:
    workbook = load_workbook(path, read_only=True, data_only=False)
    worksheet = workbook[sheet_name] if sheet_name and sheet_name in workbook.sheetnames else workbook.active
    columns = find_columns(worksheet)
    for row in worksheet.iter_rows(min_row=2, values_only=True):
        labels = tuple(str(row[columns[field]] or "").strip() for field in LABEL_FIELD_NAMES)
        yield TenderRecord(
            code=normalized_text(row[columns["code"]]),
            spanish=normalized_text(row[columns["spanish"]]),
            english=normalized_text(row[columns["english"]]),
            labels=labels,
        )
    workbook.close()


def stable_value(counter: Counter, min_support: int = 1, min_purity: float = 1.0) -> Optional[str]:
    if not counter:
        return None
    value, count = counter.most_common(1)[0]
    total = sum(counter.values())
    if count < min_support or count / total < min_purity:
        return None
    return value


def label_value_maps(records: Iterable[TenderRecord]):
    maps = {
        "code": [defaultdict(Counter) for _ in LABEL_FIELD_NAMES],
        "spanish": [defaultdict(Counter) for _ in LABEL_FIELD_NAMES],
        "english": [defaultdict(Counter) for _ in LABEL_FIELD_NAMES],
    }
    tuple_maps = {"code": defaultdict(Counter), "spanish": defaultdict(Counter), "english": defaultdict(Counter)}
    phrase_maps = [defaultdict(Counter) for _ in LABEL_FIELD_NAMES]
    manufacturer_identifier_map = defaultdict(Counter)
    family_identifier_map = defaultdict(Counter)
    family_manufacturer_map = defaultdict(Counter)
    tuple_phrase_map = defaultdict(Counter)
    label_counts = [Counter() for _ in LABEL_FIELD_NAMES]
    record_count = 0
    mapped_any = 0
    mapped_all = 0

    for record in records:
        record_count += 1
        if any(record.labels):
            mapped_any += 1
        if all(record.labels):
            mapped_all += 1
        for index, label in enumerate(record.labels):
            if not label:
                continue
            label_counts[index][label] += 1
            for key_type, key in (("code", record.code), ("spanish", record.spanish), ("english", record.english)):
                if key:
                    maps[key_type][index][key][label] += 1

        phrases = set(ngrams(tokenize(record.spanish))) | set(ngrams(tokenize(record.english)))

        if all(record.labels):
            for key_type, key in (("code", record.code), ("spanish", record.spanish), ("english", record.english)):
                if key:
                    tuple_maps[key_type][key][record.labels] += 1
            for phrase in phrases:
                tuple_phrase_map[phrase][record.labels] += 1

        for index, label in enumerate(record.labels):
            if not label:
                continue
            for phrase in phrases:
                phrase_maps[index][phrase][label] += 1

        manufacturer = record.labels[2]
        if manufacturer and not is_placeholder_label(manufacturer):
            for identifier in manufacturer_identifier_forms(manufacturer):
                manufacturer_identifier_map[identifier][manufacturer] += 1
        family = record.labels[3]
        if family and not is_placeholder_label(family):
            for identifier in family_identifier_forms(family):
                family_identifier_map[identifier][family] += 1
            if manufacturer and not is_placeholder_label(manufacturer):
                family_manufacturer_map[family][manufacturer] += 1

    return {
        "record_count": record_count,
        "mapped_any": mapped_any,
        "mapped_all": mapped_all,
        "label_counts": label_counts,
        "field_maps": maps,
        "tuple_maps": tuple_maps,
        "phrase_maps": phrase_maps,
        "manufacturer_identifier_map": manufacturer_identifier_map,
        "family_identifier_map": family_identifier_map,
        "family_manufacturer_map": family_manufacturer_map,
        "tuple_phrase_map": tuple_phrase_map,
    }


def exact_labels(record: TenderRecord, evidence) -> Tuple[List[Optional[str]], List[str]]:
    result: List[Optional[str]] = [None] * len(LABEL_FIELD_NAMES)
    sources: List[str] = [""] * len(LABEL_FIELD_NAMES)
    for key_type, key in (("spanish", record.spanish), ("english", record.english), ("code", record.code)):
        if not key:
            continue
        for index in range(len(LABEL_FIELD_NAMES)):
            # A procurement classification code identifies the product type,
            # not the manufacturer or product family.
            if key_type == "code" and index >= 2:
                continue
            if result[index] is not None:
                continue
            value = stable_value(evidence["field_maps"][key_type][index].get(key, Counter()))
            if value:
                result[index] = value
                sources[index] = f"exact_{key_type}"
    return result, sources


def phrase_labels(
    record: TenderRecord,
    evidence,
    phrase_min_support: int,
    phrase_min_words: int,
) -> Tuple[List[Optional[str]], List[str]]:
    result: List[Optional[str]] = [None] * len(LABEL_FIELD_NAMES)
    sources: List[str] = [""] * len(LABEL_FIELD_NAMES)
    phrases = set(ngrams(tokenize(record.spanish))) | set(ngrams(tokenize(record.english)))
    # Phrases can classify the clinical product, but they must not infer a
    # manufacturer or product family from a generic tender description.
    for index in range(2):
        candidates: List[Tuple[int, int, str]] = []
        for phrase in phrases:
            if len(phrase.split()) < phrase_min_words:
                continue
            labels = evidence["phrase_maps"][index].get(phrase)
            if not labels:
                continue
            value = stable_value(labels, min_support=phrase_min_support, min_purity=1.0)
            if not value:
                continue
            candidates.append((len(phrase.split()), sum(labels.values()), value))
        if not candidates:
            continue
        candidates.sort(reverse=True)
        top_width, top_support, top_value = candidates[0]
        conflicting = [candidate for candidate in candidates if candidate[2] != top_value and candidate[0] == top_width]
        if conflicting:
            continue
        result[index] = top_value
        sources[index] = f"phrase_{top_width}w_{top_support}"
    return result, sources


def identifier_value(record: TenderRecord, mapping) -> Tuple[Optional[str], str]:
    tokens = tokenize(record.spanish) + tokenize(record.english)
    terms = set(ngrams(tokens, minimum=1, maximum=6))
    candidates: List[Tuple[int, int, str]] = []
    for term in terms:
        labels = mapping.get(term)
        if not labels:
            continue
        value = stable_value(labels, min_support=1, min_purity=1.0)
        if value:
            candidates.append((len(term.split()), sum(labels.values()), value))
    if not candidates:
        return None, ""
    candidates.sort(reverse=True)
    top_width, top_support, top_value = candidates[0]
    conflicting = [candidate for candidate in candidates if candidate[2] != top_value and candidate[0] == top_width]
    if conflicting:
        return None, ""
    return top_value, f"identifier_{top_width}w_{top_support}"


def identifier_labels(
    record: TenderRecord,
    evidence,
    exact_manufacturer: Optional[str],
) -> Tuple[List[Optional[str]], List[str]]:
    manufacturer, manufacturer_source = identifier_value(record, evidence["manufacturer_identifier_map"])
    effective_manufacturer = exact_manufacturer or manufacturer
    family = None
    family_source = ""
    if effective_manufacturer:
        candidate_family, candidate_source = identifier_value(record, evidence["family_identifier_map"])
        if candidate_family:
            expected_manufacturer = stable_value(evidence["family_manufacturer_map"].get(candidate_family, Counter()))
            if expected_manufacturer == effective_manufacturer:
                family = candidate_family
                family_source = candidate_source
    return [None, None, manufacturer, family], ["", "", manufacturer_source, family_source]


def merge_labels(
    exact: List[Optional[str]],
    exact_sources: List[str],
    phrase: List[Optional[str]],
    phrase_sources: List[str],
    identifiers: List[Optional[str]],
    identifier_sources: List[str],
):
    values: List[Optional[str]] = []
    sources: List[str] = []
    for exact_value, exact_source, phrase_value, phrase_source, identifier_value_, identifier_source in zip(
        exact,
        exact_sources,
        phrase,
        phrase_sources,
        identifiers,
        identifier_sources,
    ):
        if exact_value:
            values.append(exact_value)
            sources.append(exact_source)
        elif phrase_value:
            values.append(phrase_value)
            sources.append(phrase_source)
        else:
            values.append(identifier_value_)
            sources.append(identifier_source)
    return values, sources


def audit_records(
    records: Iterable[TenderRecord],
    evidence,
    phrase_min_support: int,
    phrase_min_words: int,
) -> Dict[str, object]:
    counts = Counter()
    per_field = [Counter() for _ in LABEL_FIELD_NAMES]
    mapped_by_source = Counter()
    for record in records:
        exact, exact_sources = exact_labels(record, evidence)
        phrase, phrase_sources = phrase_labels(
            record,
            evidence,
            phrase_min_support=phrase_min_support,
            phrase_min_words=phrase_min_words,
        )
        identifiers, identifier_sources = identifier_labels(record, evidence, exact_manufacturer=exact[2])
        values, sources = merge_labels(exact, exact_sources, phrase, phrase_sources, identifiers, identifier_sources)
        for index, value in enumerate(values):
            if value:
                per_field[index]["mapped"] += 1
                mapped_by_source[sources[index].split("_")[0]] += 1
            else:
                per_field[index]["blank"] += 1
        if all(values):
            counts["all_four"] += 1
        elif any(values):
            counts["partial"] += 1
        else:
            counts["unmapped"] += 1
        counts["rows"] += 1
    return {
        "target_rows": counts["rows"],
        "all_four": counts["all_four"],
        "partial": counts["partial"],
        "unmapped": counts["unmapped"],
        "per_field": {LABEL_FIELD_NAMES[index]: dict(counter) for index, counter in enumerate(per_field)},
        "mapped_by_source": dict(mapped_by_source),
    }


def write_mapped_workbook(
    source: Path,
    output: Path,
    evidence,
    phrase_min_support: int,
    phrase_min_words: int,
) -> Dict[str, object]:
    temporary = output.with_suffix(".in_progress.xlsx")
    shutil.copy2(source, temporary)
    workbook = load_workbook(temporary, data_only=False)
    worksheet = workbook.active
    columns = find_columns(worksheet)
    counts = Counter()

    for row_number in range(2, worksheet.max_row + 1):
        record = TenderRecord(
            code=normalized_text(worksheet.cell(row_number, columns["code"] + 1).value),
            spanish=normalized_text(worksheet.cell(row_number, columns["spanish"] + 1).value),
            english=normalized_text(worksheet.cell(row_number, columns["english"] + 1).value),
            labels=("", "", "", ""),
        )
        exact, exact_sources = exact_labels(record, evidence)
        phrase, phrase_sources = phrase_labels(
            record,
            evidence,
            phrase_min_support=phrase_min_support,
            phrase_min_words=phrase_min_words,
        )
        identifiers, identifier_sources = identifier_labels(record, evidence, exact_manufacturer=exact[2])
        values, sources = merge_labels(exact, exact_sources, phrase, phrase_sources, identifiers, identifier_sources)
        for index, field in enumerate(LABEL_FIELD_NAMES):
            value = values[index]
            if value:
                worksheet.cell(row_number, columns[LABEL_FIELD_NAMES[index]] + 1).value = value
                counts[f"{LABEL_FIELD_NAMES[index]}:{sources[index]}"] += 1
            else:
                counts[f"{LABEL_FIELD_NAMES[index]}:blank"] += 1

    try:
        workbook.calculation.fullCalcOnLoad = True
        workbook.calculation.forceFullCalc = True
        workbook.calculation.calcMode = "auto"
    except AttributeError:
        pass
    workbook.save(temporary)
    workbook.close()
    temporary.replace(output)
    return dict(counts)


def make_summary(evidence, target_audit: Dict[str, object]) -> Dict[str, object]:
    stable = {}
    for key_type, field_maps in evidence["field_maps"].items():
        stable[key_type] = {}
        for index, mapping in enumerate(field_maps):
            stable[key_type][LABEL_FIELD_NAMES[index]] = sum(
                1 for key, counter in mapping.items() if key and stable_value(counter)
            )
    return {
        "historical_rows": evidence["record_count"],
        "historical_rows_with_any_mapping": evidence["mapped_any"],
        "historical_rows_with_all_four": evidence["mapped_all"],
        "historical_unique_labels": {
            LABEL_FIELD_NAMES[index]: len(counter) for index, counter in enumerate(evidence["label_counts"])
        },
        "stable_exact_keys": stable,
        "target_coverage": target_audit,
    }


def parser() -> argparse.ArgumentParser:
    argument_parser = argparse.ArgumentParser(description=__doc__)
    argument_parser.add_argument("--historical", type=Path, action="append", required=True, help="Reviewed historical workbook. Repeatable.")
    argument_parser.add_argument("--source", type=Path, required=True, help="FY27 Q1 workbook to map.")
    argument_parser.add_argument("--audit-json", type=Path, required=True, help="Path for the mapping audit JSON.")
    argument_parser.add_argument("--output", type=Path, help="Mapped workbook path. Omit for audit-only mode.")
    argument_parser.add_argument(
        "--phrase-min-support",
        type=int,
        default=3,
        help="Minimum unanimous historical examples required for a phrase mapping (default: 3).",
    )
    argument_parser.add_argument(
        "--phrase-min-words",
        type=int,
        default=3,
        help="Minimum number of words required in a product-classification phrase (default: 3).",
    )
    return argument_parser


def main() -> int:
    args = parser().parse_args()
    if args.phrase_min_support < 1 or args.phrase_min_words < 2:
        raise ValueError("Mapping support thresholds must be at least 1.")
    records: List[TenderRecord] = []
    for historical_path in args.historical:
        records.extend(iter_records(historical_path))
    evidence = label_value_maps(records)
    target_records = list(iter_records(args.source, sheet_name=None))
    target_audit = audit_records(
        target_records,
        evidence,
        phrase_min_support=args.phrase_min_support,
        phrase_min_words=args.phrase_min_words,
    )
    summary = make_summary(evidence, target_audit)
    args.audit_json.parent.mkdir(parents=True, exist_ok=True)
    args.audit_json.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        mapping_counts = write_mapped_workbook(
            args.source,
            args.output,
            evidence,
            phrase_min_support=args.phrase_min_support,
            phrase_min_words=args.phrase_min_words,
        )
        print(json.dumps({"mapping_counts": mapping_counts, "output": str(args.output)}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
