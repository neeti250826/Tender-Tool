from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harness.shared.schema import OUTPUT_COLUMNS


ITEM_QTY_RE = re.compile(
    r"\b(\d+(?:[.,]\d+)?)\s*(buc\.?|bucati|bucăți|unitati|unități|seturi|kituri|flacoane|fiole|cutii|teste|doze)\b",
    re.I,
)
CONTRACT_PERIOD_RE = re.compile(
    r"\b(?:durata|termen(?:ul)?|perioada|livrare|execu[țt]ie|contract(?:ului)?)\D{0,80}"
    r"(\d+(?:[.,]\d+)?)\s*(zile|luni|ani|days?|months?|years?)\b",
    re.I,
)


def _decimal_text(value: str) -> str:
    cleaned = (value or "").strip().replace(" ", "")
    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")
    return cleaned


def _unit_price(value: str, quantity: str) -> str:
    try:
        value_num = Decimal(_decimal_text(value))
        quantity_num = Decimal(_decimal_text(quantity))
    except InvalidOperation:
        return ""
    if not quantity_num:
        return ""
    result = value_num / quantity_num
    return f"{result:.6f}".rstrip("0").rstrip(".")


def _first_match(pattern: re.Pattern[str], text: str) -> tuple[str, str]:
    match = pattern.search(text)
    if not match:
        return "", ""
    return match.group(1).strip(), match.group(2).strip().rstrip(".")


def enrich_file(input_path: Path, output_path: Path, audit_path: Path) -> dict[str, object]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    counts = {
        "rows": 0,
        "item_quantity_filled": 0,
        "item_uom_filled": 0,
        "item_unit_price_filled": 0,
        "contract_period_filled": 0,
    }
    nonempty = {column: 0 for column in OUTPUT_COLUMNS}

    with input_path.open("r", encoding="utf-8", newline="") as source, output_path.open(
        "w", encoding="utf-8", newline=""
    ) as target:
        reader = csv.DictReader(source)
        writer = csv.DictWriter(target, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        for row in reader:
            counts["rows"] += 1
            text = " ".join([row.get("item_desc", ""), row.get("description", ""), row.get("title", "")])

            if not row.get("item_quantity") or not row.get("item_uom"):
                quantity, uom = _first_match(ITEM_QTY_RE, text)
                if quantity and not row.get("item_quantity"):
                    row["item_quantity"] = quantity
                    counts["item_quantity_filled"] += 1
                if uom and not row.get("item_uom"):
                    row["item_uom"] = uom
                    counts["item_uom_filled"] += 1

            if not row.get("item_unit_price") and row.get("awarded_value") and row.get("item_quantity"):
                unit_price = _unit_price(row["awarded_value"], row["item_quantity"])
                if unit_price:
                    row["item_unit_price"] = unit_price
                    counts["item_unit_price_filled"] += 1

            if not row.get("contract_period"):
                duration, unit = _first_match(CONTRACT_PERIOD_RE, text)
                if duration and unit:
                    row["contract_period"] = f"{duration} {unit}"
                    counts["contract_period_filled"] += 1

            normalized = {column: row.get(column, "") for column in OUTPUT_COLUMNS}
            for column, value in normalized.items():
                if (value or "").strip():
                    nonempty[column] += 1
            writer.writerow(normalized)

    audit = {
        "input": str(input_path),
        "output": str(output_path),
        "counts": counts,
        "nonempty": nonempty,
        "blanks": {column: counts["rows"] - nonempty[column] for column in OUTPUT_COLUMNS},
    }
    audit_path.write_text(json.dumps(audit, indent=2), encoding="utf-8")
    return audit


def main() -> int:
    parser = argparse.ArgumentParser(description="Evidence-backed text enrichment for Romania TED normalized rows.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--audit", required=True)
    args = parser.parse_args()
    audit = enrich_file(Path(args.input), Path(args.output), Path(args.audit))
    print(json.dumps(audit["counts"], indent=2))
    print(Path(args.output).resolve())
    print(Path(args.audit).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
