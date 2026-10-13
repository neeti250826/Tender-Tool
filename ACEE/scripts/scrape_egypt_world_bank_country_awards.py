from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Iterable

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harness.shared.normalize import normalize_text, utc_now_iso
from harness.shared.schema import OutputRow
from harness.shared.serialize import write_rows_csv


WB_EGYPT_AWARDS_CSV = (
    "https://financesonefiles.worldbank.org/f-one/DS01057/"
    "Contract_Awards_in_Investment_Project_Financing___Egypt_Projects.csv"
)

PROCUREMENT_PLAN_URLS = (
    (
        "P172548",
        "https://documents1.worldbank.org/curated/en/099050725133028592/txt/"
        "P172548-6f9dfc97-b0f4-4c1c-bfc7-ad75d82ea38b.txt",
        "world_bank_p172548_procurement_plan_2025_05_07.txt",
    ),
    (
        "P172548",
        "https://documents1.worldbank.org/curated/en/099060325213025294/txt/"
        "P172548-33fa6f87-2137-45c8-8a0e-f9a034be535a.txt",
        "world_bank_p172548_procurement_plan_2025_06_03.txt",
    ),
    (
        "P172426",
        "https://documents1.worldbank.org/curated/en/099080325083540214/txt/"
        "P172426-08832782-6b6e-4bf8-a841-874526eccf3d.txt",
        "world_bank_p172426_procurement_plan_2025_08_03.txt",
    ),
    (
        "P172426",
        "https://documents1.worldbank.org/curated/en/099111725063831843/txt/"
        "P172426-dd5a6fe8-fb78-44e3-b809-261d6ac4113c.txt",
        "world_bank_p172426_procurement_plan_2025_11_17.txt",
    ),
)

P172426_RELEVANCE_TERMS = (
    "universal health insurance",
    "uhia",
    "gahc",
    "gahar",
    "health economist",
    "health insurance",
)

P172548_RELEVANCE_TERMS = (
    "laboratory",
    "medical waste",
    "healthcare waste",
    "hospital",
)


def _clean(value: str | None) -> str:
    return normalize_text(value or "")


def _iter_awards(timeout: int) -> Iterable[dict[str, str]]:
    response = requests.get(WB_EGYPT_AWARDS_CSV, timeout=timeout)
    response.raise_for_status()
    response.encoding = "utf-8-sig"
    yield from csv.DictReader(response.text.splitlines())


def _download_plan_texts(evidence_dir: Path, timeout: int) -> dict[str, str]:
    texts: dict[str, list[str]] = {}
    evidence_dir.mkdir(parents=True, exist_ok=True)
    for project_id, url, filename in PROCUREMENT_PLAN_URLS:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        response.encoding = "utf-8"
        text = response.text
        (evidence_dir / filename).write_text(text, encoding="utf-8")
        texts.setdefault(project_id, []).append(text)
    return {project_id: "\n\n".join(parts) for project_id, parts in texts.items()}


def _plan_block(plan_text: str, reference: str) -> str:
    reference = _clean(reference)
    if not reference:
        return ""
    start = plan_text.find(reference)
    if start < 0:
        return ""
    next_match = re.search(r"\n\s*EG-[A-Z0-9-]+", plan_text[start + len(reference) :])
    end = start + len(reference) + next_match.start() if next_match else len(plan_text)
    return plan_text[start:end]


def _split_plan_dates(block: str) -> list[str]:
    lines = block.splitlines()
    for index, line in enumerate(lines):
        months = re.findall(r"(20\d{2})-(\d{2})-", line)
        if not months:
            continue
        for candidate in lines[index + 1 : index + 6]:
            days = [
                day
                for day in re.findall(r"\b(\d{2})\b", candidate)
                if 1 <= int(day) <= 31
            ]
            if len(days) >= len(months):
                return [f"{year}-{month}-{day}" for (year, month), day in zip(months, days)]
    return []


def _plan_dates(block: str) -> list[str]:
    dates = re.findall(r"20\d{2}-\d{2}-\d{2}", block)
    return dates or _split_plan_dates(block)


def _publication_date(block: str) -> str:
    dates = _plan_dates(block)
    if len(dates) >= 8:
        return dates[3]
    if len(dates) >= 2:
        return dates[1]
    return dates[0] if dates else ""


def _contract_period(block: str, signing_date: str) -> str:
    dates = _plan_dates(block)
    if not dates:
        return ""
    completion = dates[-1]
    if signing_date:
        return f"Signed contract {signing_date}; planned contract completion {completion}"
    if len(dates) >= 2:
        return f"Signed contract {dates[-2]}; planned contract completion {completion}"
    return ""


def _item_measure(text: str) -> tuple[str, str]:
    text = _clean(text)
    lot_words = {
        "one": "1",
        "two": "2",
        "three": "3",
        "four": "4",
        "five": "5",
        "six": "6",
    }
    pdf_wrapped_lot_match = re.search(
        r"\(\s*(one|two|three|four|five|six|\d+)(?:\s+[A-Za-z]{1,4})?\s+lots?\s*\)",
        text,
        re.I,
    )
    if pdf_wrapped_lot_match:
        quantity = lot_words.get(pdf_wrapped_lot_match.group(1).lower(), pdf_wrapped_lot_match.group(1))
        return "lot", quantity
    lot_match = re.search(r"\b(one|two|three|four|five|six|\d+)\s+lots?\b", text, re.I)
    if lot_match:
        quantity = lot_words.get(lot_match.group(1).lower(), lot_match.group(1))
        return "lot", quantity
    quantity_match = re.search(r"\bQuantity\s*:\s*([0-9,]+)\s*([A-Za-z][A-Za-z /-]*)?", text, re.I)
    if quantity_match:
        quantity = quantity_match.group(1).replace(",", "")
        unit = _clean(quantity_match.group(2) or "")
        return unit, quantity
    return "", ""


def _item_no(description: str) -> str:
    match = re.search(r"\bLOT\s*([0-9]+)\b", description or "", re.I)
    return match.group(1) if match else "1"


def _is_healthcare_relevant(row: dict[str, str]) -> bool:
    project_id = _clean(row.get("project_id", ""))
    description = _clean(row.get("contract_description", "")).lower()
    if project_id == "P172426":
        return any(term in description for term in P172426_RELEVANCE_TERMS)
    if project_id == "P172548":
        return any(term in description for term in P172548_RELEVANCE_TERMS)
    return False


def collect_rows(
    *,
    start_date: str,
    end_date: str,
    evidence_dir: Path,
    timeout: int,
    query_text: str,
) -> tuple[list[dict[str, str]], dict[str, object]]:
    plan_texts = _download_plan_texts(evidence_dir, timeout)
    scraped_at = utc_now_iso()
    rows: list[dict[str, str]] = []

    for source_row in _iter_awards(timeout):
        signing_date = _clean(source_row.get("contract_signing_date", ""))
        if not (start_date <= signing_date <= end_date):
            continue
        project_id = _clean(source_row.get("project_id", ""))
        if project_id == "P167000":
            continue
        if not _is_healthcare_relevant(source_row):
            continue

        description = _clean(source_row.get("contract_description", ""))
        project = _clean(source_row.get("project_name", ""))
        reference = _clean(source_row.get("borrower_contract_reference_number", ""))
        amount = _clean(source_row.get("supplier_contract_amount_usd", ""))
        plan_block = _plan_block(plan_texts.get(project_id, ""), reference)
        publication_date = _publication_date(plan_block)
        contract_period = _contract_period(plan_block, signing_date)
        item_uom, item_quantity = _item_measure(description)
        item_measure_source = "award_description" if item_uom and item_quantity else "not_exposed"
        if (not item_uom or not item_quantity) and plan_block:
            item_uom, item_quantity = _item_measure(plan_block)
            item_measure_source = "World Bank STEP description" if item_uom and item_quantity else "not_exposed"

        row = OutputRow(
            source="World Bank Egypt IPF contract awards + STEP procurement plan",
            country="Egypt",
            country_cc="EG",
            publication_date=publication_date,
            title=description,
            description=project,
            classification=_clean(source_row.get("procurement_category", "")),
            status="Awarded",
            currency="USD" if amount else "",
            amount=amount,
            awarding_supplier_name=_clean(source_row.get("supplier", "")),
            awarded_currency="USD" if amount else "",
            awarded_value=amount,
            contract_period=contract_period,
            item_no=_item_no(description),
            item_desc=description,
            item_uom=item_uom,
            item_quantity=item_quantity,
            item_award=signing_date,
            notice_id=_clean(source_row.get("wb_contract_number", "")) or reference,
            notice_url=WB_EGYPT_AWARDS_CSV,
            query_text=(
                f"{query_text}; project_id={project_id}; borrower_reference={reference}; "
                f"publication_date_source=World Bank STEP date when matched; "
                f"healthcare_relevance_filter=contract/project text; "
                f"item_measure_source={item_measure_source}"
            ),
            scraped_at=scraped_at,
            dedup_key=f"world_bank_egypt_ipf_awards|EG|{source_row.get('wb_contract_number') or reference}",
        ).to_dict()
        rows.append(row)

    summary = {
        "rows": len(rows),
        "publication_date": sum(1 for row in rows if row.get("publication_date")),
        "contract_period": sum(1 for row in rows if row.get("contract_period")),
        "awarding_supplier_name": sum(1 for row in rows if row.get("awarding_supplier_name")),
        "amount_or_awarded_value": sum(1 for row in rows if row.get("amount") or row.get("awarded_value")),
        "item_uom": sum(1 for row in rows if row.get("item_uom")),
        "item_quantity": sum(1 for row in rows if row.get("item_quantity")),
        "rows_with_all_required_fields": sum(
            1
            for row in rows
            if all(
                row.get(field)
                for field in (
                    "publication_date",
                    "amount",
                    "contract_period",
                    "awarding_supplier_name",
                    "item_award",
                    "item_uom",
                    "item_quantity",
                    "item_no",
                    "item_desc",
                )
            )
        ),
    }
    return rows, summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scrape supplemental Egypt healthcare/lab World Bank country awards.")
    parser.add_argument("--start-date", default="2024-01-01")
    parser.add_argument("--end-date", default=date.today().isoformat())
    parser.add_argument("--output-dir", default="Egypt/world-bank-egypt-ipf-awards")
    parser.add_argument("--evidence-dir", default="evidence/egypt_extended_award_probe_2026_06_24")
    parser.add_argument("--timeout", type=int, default=60)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    stamp = args.end_date.replace("-", "_")
    rows, summary = collect_rows(
        start_date=args.start_date,
        end_date=args.end_date,
        evidence_dir=Path(args.evidence_dir),
        timeout=args.timeout,
        query_text=f"live:world-bank-egypt-ipf-healthcare-lab-awards:{args.start_date}_to_{args.end_date}",
    )
    output_dir = Path(args.output_dir)
    output_path = output_dir / f"healthcare_lab_awarded_contracts_{args.start_date}_to_{stamp}.csv"
    latest_path = output_dir / "healthcare_lab_awarded_contracts_latest.csv"
    summary_path = output_dir / f"healthcare_lab_awarded_contracts_summary_{stamp}.json"
    write_rows_csv(output_path, rows)
    write_rows_csv(latest_path, rows)
    summary["output"] = str(output_path)
    summary["latest_output"] = str(latest_path)
    summary["evidence_dir"] = args.evidence_dir
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
