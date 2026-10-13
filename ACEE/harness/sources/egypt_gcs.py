from __future__ import annotations

import re
from html import unescape
from pathlib import Path

from bs4 import BeautifulSoup

from harness.shared.normalize import normalize_text, utc_now_iso
from harness.shared.schema import OutputRow
from harness.sources.base import SmokeProbeResult
from harness.sources.registry import SOURCES

CONFIG = SOURCES["egypt_gcs"]
EVIDENCE_PATH = Path("evidence") / "egypt_gcs_tender_detail_sample.html"
HOME_EVIDENCE_PATH = Path("evidence") / "egypt_gcs_home.html"
NOTICE_URL = "https://gcs.digitalegypt.gov.eg/Landing/TenderDetails/0daca665-2e7a-4ac7-99f8-87e352ada313"

HOME_FIELD_LABELS = {
    "اخر تاريخ لتلقى الطلبات": "closing_date",
    "تاريخ الطرح": "publication_date_home",
}

HOME_CARD_FIELD_LABELS = {
    "اسم العملية": "title",
    "الجهة": "buyer",
    "طبيعة العملية": "classification",
    "اخر تاريخ لتلقى الطلبات": "closing_date",
    "تاريخ الطرح": "publication_date",
}

FIELD_LABELS = {
    "اسم العملية": "title",
    "اسم الجهه": "buyer",
    "رقم العملية": "notice_id",
    "العملة": "currency",
    "الوصف باللغة العربية": "description",
    "الأنشطة": "classification",
    "تاريخ الإعلان / الدعوة": "publication_date",
    "تاريخ فتح المظاريف الفنية": "closing_date",
    "تاريخ الترسية": "award_date",
    "مدة التوريد / التنفيذ": "contract_period",
}

ITEM_LABELS = {
    "البند": "item_desc",
    "الوحدة": "item_uom",
    "الكمية المطلوبة": "item_quantity",
}

MEDICAL_PATTERNS = (
    "طبي",
    "طبية",
    "صحي",
    "صحية",
    "مستشفى",
    "اسعاف",
    "دواء",
    "صيدلية",
)

NON_MEDICAL_HOME_PATTERNS = (
    "بيع",
    "انتفاع",
    "عقارات",
    "محلات",
    "وحدات ادارية",
    "وحدات إدارية",
    "طباعة",
    "حبر",
    "ريبون",
)


def _load_text() -> str:
    return EVIDENCE_PATH.read_text(encoding="utf-8", errors="ignore")


def _load_home_text() -> str:
    if not HOME_EVIDENCE_PATH.exists():
        return ""
    return HOME_EVIDENCE_PATH.read_text(encoding="utf-8", errors="ignore")


def _strip_html(value: str) -> str:
    return normalize_text(unescape(re.sub(r"<[^>]+>", " ", value)))


def _extract_labeled_fields(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    soup = BeautifulSoup(text, "html.parser")
    for block in soup.select("div.p-3.d-flex.flex-column"):
        label_tag = block.find("label")
        value_tag = block.find("p", class_="m-0")
        if not label_tag or not value_tag:
            continue
        label = normalize_text(label_tag.get_text(" ", strip=True))
        value = normalize_text(value_tag.get_text(" ", strip=True))
        target = FIELD_LABELS.get(label)
        if not target:
            continue
        fields[target] = "" if value == "لا يوجد" else value
    return fields


def _extract_item_blocks(text: str) -> list[dict[str, str]]:
    blocks: list[dict[str, str]] = []
    soup = BeautifulSoup(text, "html.parser")
    for block in soup.select("div.row.py-3.px-2.m-0.bg-gray.info"):
        item: dict[str, str] = {}
        for cell in block.select("div.col-md-4"):
            label_tag = cell.find("label")
            value_tag = cell.find("p", class_="m-0")
            if not label_tag or not value_tag:
                continue
            label = normalize_text(label_tag.get_text(" ", strip=True))
            value = normalize_text(value_tag.get_text(" ", strip=True))
            target = ITEM_LABELS.get(label)
            if target:
                item[target] = value
        _refine_item_fields_from_text(item)
        if item:
            blocks.append(item)
    return blocks


def _refine_item_fields_from_text(item: dict[str, str]) -> None:
    item_desc = normalize_text(item.get("item_desc", ""))
    item_quantity = normalize_text(item.get("item_quantity", ""))
    item_uom = normalize_text(item.get("item_uom", ""))

    quantity_match = re.search(r"شراء\s*(\d+)\s*(?:اجهزة|أجهزة|جهاز|وحدات)", item_desc)
    if quantity_match and item_quantity in {"", "1"}:
        item["item_quantity"] = quantity_match.group(1)
        if item_uom in {"", "بكرة"}:
            item["item_uom"] = "جهاز"


def _extract_home_card_fields(text: str, notice_url: str) -> dict[str, str]:
    if not text:
        return {}
    notice_path = notice_url.replace("https://gcs.digitalegypt.gov.eg", "")
    path_pattern = re.escape(notice_path)
    block_match = re.search(rf'href="{path_pattern}"(?P<block>.*?)</a>', text, re.S)
    if not block_match:
        return {}
    fields: dict[str, str] = {}
    block = block_match.group("block")
    for label, target in HOME_FIELD_LABELS.items():
        match = re.search(
            rf"{re.escape(label)}.*?<p class=\"m-0\">(.*?)</p>",
            block,
            re.S,
        )
        if match:
            fields[target] = _strip_html(match.group(1))
    return fields


def _extract_home_cards(text: str) -> list[dict[str, str]]:
    if not text:
        return []
    soup = BeautifulSoup(text, "html.parser")
    cards: list[dict[str, str]] = []
    for link in soup.select('a[href^="/Landing/TenderDetails/"]'):
        notice_path = normalize_text(link.get("href"))
        if not notice_path:
            continue
        card: dict[str, str] = {
            "notice_url": f"https://gcs.digitalegypt.gov.eg{notice_path}",
            "status": "Published",
        }
        for block in link.select("div.p-3.d-flex.flex-column"):
            label_tag = block.find("label")
            value_tag = block.find("p", class_="m-0")
            if not label_tag or not value_tag:
                continue
            label = normalize_text(label_tag.get_text(" ", strip=True))
            value = normalize_text(value_tag.get_text(" ", strip=True))
            target = HOME_CARD_FIELD_LABELS.get(label)
            if target:
                card[target] = value
        if card.get("title"):
            cards.append(card)
    return cards


def _is_medical_home_card(card: dict[str, str]) -> bool:
    haystack = " ".join(normalize_text(card.get(field, "")).lower() for field in ("title", "buyer", "classification"))
    if any(pattern.lower() in haystack for pattern in NON_MEDICAL_HOME_PATTERNS):
        return False
    return any(pattern.lower() in haystack for pattern in MEDICAL_PATTERNS)


def map_notice_to_rows(query_text: str = "") -> list[dict[str, str]]:
    text = _load_text()
    home_text = _load_home_text()
    fields = _extract_labeled_fields(text)
    home_fields = _extract_home_card_fields(home_text, NOTICE_URL)
    items = _extract_item_blocks(text) or [{}]

    rows: list[dict[str, str]] = []
    for index, item in enumerate(items, start=1):
        item_desc = item.get("item_desc", "")
        description = fields.get("description", "") or item_desc or fields.get("title", "")
        status = "Awarded" if fields.get("award_date") else "Published"
        row = OutputRow(
            source=CONFIG.source,
            country=CONFIG.country,
            country_cc=CONFIG.country_cc,
            publication_date=fields.get("publication_date", ""),
            closing_date=home_fields.get("closing_date", "") or fields.get("closing_date", ""),
            title=fields.get("title", ""),
            description=description,
            buyer=fields.get("buyer", ""),
            classification=fields.get("classification", ""),
            status=status,
            currency=fields.get("currency", ""),
            contract_period=fields.get("contract_period", ""),
            item_no=str(index),
            item_desc=item_desc,
            item_uom=item.get("item_uom", ""),
            item_quantity=item.get("item_quantity", ""),
            notice_id=fields.get("notice_id", ""),
            notice_url=NOTICE_URL,
            query_text=query_text,
            scraped_at=utc_now_iso(),
            dedup_key=f"{CONFIG.key}|{fields.get('notice_id', '')}|{index}",
        )
        rows.append(row.to_dict())
    return rows


def home_snapshot_rows(query_text: str = "") -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for card in _extract_home_cards(_load_home_text()):
        notice_url = card.get("notice_url", "")
        notice_id = notice_url.rstrip("/").split("/")[-1] if notice_url else ""
        row = OutputRow(
            source=CONFIG.source,
            country=CONFIG.country,
            country_cc=CONFIG.country_cc,
            publication_date=card.get("publication_date", ""),
            closing_date=card.get("closing_date", ""),
            title=card.get("title", ""),
            description=card.get("title", ""),
            buyer=card.get("buyer", ""),
            classification=card.get("classification", ""),
            status=card.get("status", "Published"),
            notice_id=notice_id,
            notice_url=notice_url,
            query_text=query_text,
            scraped_at=utc_now_iso(),
            dedup_key=f"{CONFIG.key}|home-card|{notice_id}",
        )
        rows.append(row.to_dict())
    return rows


def home_snapshot_medical_rows(query_text: str = "") -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for card in _extract_home_cards(_load_home_text()):
        if not _is_medical_home_card(card):
            continue
        notice_url = card.get("notice_url", "")
        notice_id = notice_url.rstrip("/").split("/")[-1] if notice_url else ""
        row = OutputRow(
            source=CONFIG.source,
            country=CONFIG.country,
            country_cc=CONFIG.country_cc,
            publication_date=card.get("publication_date", ""),
            closing_date=card.get("closing_date", ""),
            title=card.get("title", ""),
            description=card.get("title", ""),
            buyer=card.get("buyer", ""),
            classification=card.get("classification", ""),
            status=card.get("status", "Published"),
            notice_id=notice_id,
            notice_url=notice_url,
            query_text=query_text,
            scraped_at=utc_now_iso(),
            dedup_key=f"{CONFIG.key}|home-card-medical|{notice_id}",
        )
        rows.append(row.to_dict())
    return rows


def smoke_probe() -> SmokeProbeResult:
    rows = map_notice_to_rows(query_text="fixture:public-tender-detail")
    row = rows[0] if rows else {}
    return SmokeProbeResult(
        source_key=CONFIG.key,
        ok=bool(rows)
        and all(
            [
                row["notice_id"],
                row["title"],
                row["buyer"],
                row["publication_date"],
                row["closing_date"],
                row["currency"],
                row["contract_period"],
                row["item_desc"],
                row["item_uom"],
                row["item_quantity"],
                row["status"] == "Awarded",
                not row["awarding_supplier_name"],
                not row["awarded_currency"],
                not row["awarded_value"],
            ]
        ),
        mode="fixture",
        detail="Mapped one public GCS tender detail page plus homepage card into one fixture-backed awarded row without inventing award-side values.",
        sample_rows=rows,
    )
