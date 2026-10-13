from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Dict, List


OUTPUT_COLUMNS: List[str] = [
    "source",
    "country",
    "country_cc",
    "publication_date",
    "closing_date",
    "title",
    "description",
    "buyer",
    "classification",
    "status",
    "currency",
    "amount",
    "awarding_supplier_name",
    "awarded_currency",
    "awarded_value",
    "contract_period",
    "item_no",
    "item_desc",
    "item_uom",
    "item_quantity",
    "item_unit_price",
    "item_award",
    "notice_id",
    "notice_url",
    "query_text",
    "scraped_at",
    "dedup_key",
]


@dataclass
class OutputRow:
    source: str = ""
    country: str = ""
    country_cc: str = ""
    publication_date: str = ""
    closing_date: str = ""
    title: str = ""
    description: str = ""
    buyer: str = ""
    classification: str = ""
    status: str = ""
    currency: str = ""
    amount: str = ""
    awarding_supplier_name: str = ""
    awarded_currency: str = ""
    awarded_value: str = ""
    contract_period: str = ""
    item_no: str = ""
    item_desc: str = ""
    item_uom: str = ""
    item_quantity: str = ""
    item_unit_price: str = ""
    item_award: str = ""
    notice_id: str = ""
    notice_url: str = ""
    query_text: str = ""
    scraped_at: str = ""
    dedup_key: str = ""

    def to_dict(self) -> Dict[str, str]:
        return asdict(self)


def blank_row() -> Dict[str, str]:
    return OutputRow().to_dict()

