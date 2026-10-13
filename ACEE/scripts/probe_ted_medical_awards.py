from __future__ import annotations

import argparse
import csv
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harness.shared.normalize import normalize_text, repair_mojibake, utc_now_iso
from harness.shared.schema import OUTPUT_COLUMNS, OutputRow


TED_SEARCH_URL = "https://api.ted.europa.eu/v3/notices/search"
DEFAULT_MEDICAL_CPVS = (
    "33100000",
    "33110000",
    "33111000",
    "33111720",
    "33111721",
    "33112000",
    "33112200",
    "33112340",
    "33113000",
    "33120000",
    "33123000",
    "33130000",
    "33140000",
    "33141000",
    "33141120",
    "33141125",
    "33141200",
    "33141300",
    "33141600",
    "33141613",
    "33141621",
    "33141625",
    "33141700",
    "33150000",
    "33151000",
    "33152000",
    "33153000",
    "33155000",
    "33157000",
    "33158000",
    "33158210",
    "33160000",
    "33161000",
    "33162000",
    "33162100",
    "33162200",
    "33163000",
    "33164000",
    "33166000",
    "33168000",
    "33168100",
    "33169000",
    "33169300",
    "33170000",
    "33171000",
    "33172000",
    "33180000",
    "33181000",
    "33181500",
    "33182220",
    "33182000",
    "33183000",
    "33183200",
    "33184000",
    "33184100",
    "33190000",
    "33191000",
    "33192000",
    "33193000",
    "33194000",
    "33194120",
    "33195000",
    "33196000",
    "33197000",
    "33198000",
    "33199000",
    "33600000",
    "33651600",
    "33690000",
    "33696200",
    "33696300",
    "33696500",
    "33751000",
    "33793000",
    "50421000",
)
NS = {
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    "efac": "http://data.europa.eu/p27/eforms-ubl-extension-aggregate-components/1",
    "efbc": "http://data.europa.eu/p27/eforms-ubl-extension-basic-components/1",
}


def _text(value: object) -> str:
    return normalize_text(repair_mojibake(value))


def _first_text(node: ET.Element | None, xpath: str) -> str:
    if node is None:
        return ""
    found = node.find(xpath, NS)
    return _text(found.text if found is not None else "")


def _parse_date(value: str) -> str:
    cleaned = _text(value)
    if not cleaned:
        return ""
    cleaned = re.sub(r"([+-]\d{2}):?(\d{2})$", "", cleaned).rstrip("Z")
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(cleaned[:19], fmt).date().isoformat()
        except ValueError:
            continue
    return cleaned[:10]


def _preferred_i18n(value: Any) -> str:
    if isinstance(value, str):
        return _text(value)
    if isinstance(value, list):
        return _text(value[0]) if value else ""
    if isinstance(value, dict):
        for lang in ("eng", "hun", "ron"):
            if lang in value:
                return _preferred_i18n(value[lang])
        for nested in value.values():
            text = _preferred_i18n(nested)
            if text:
                return text
    return ""


def _list_i18n(value: Any) -> list[str]:
    if isinstance(value, list):
        return [_text(item) for item in value if _text(item)]
    if isinstance(value, dict):
        for lang in ("eng", "hun", "ron"):
            if lang in value:
                return _list_i18n(value[lang])
        for nested in value.values():
            items = _list_i18n(nested)
            if items:
                return items
    text = _preferred_i18n(value)
    return [text] if text else []


def _dedupe_preserve(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _search_notices(
    country_code: str,
    date_from: str,
    date_to: str,
    *,
    cpv: str,
    page: int,
    limit: int,
) -> list[dict[str, Any]]:
    query = (
        f"buyer-country = {country_code} "
        f"AND publication-date >= {date_from.replace('-', '')} "
        f"AND publication-date <= {date_to.replace('-', '')} "
        f"AND main-classification-proc = {cpv}"
    )
    body = {
        "query": query,
        "fields": [
            "publication-number",
            "publication-date",
            "buyer-country",
            "title-proc",
            "title-lot",
            "description-proc",
            "buyer-name",
            "winner-name",
            "winner-decision-date",
            "total-value",
            "tender-value",
            "tender-value-cur",
            "BT-660-LotResult",
            "BT-660-LotResult-Currency",
            "BT-711-LotResult",
            "BT-711-LotResult-Currency",
            "BT-720-Tender",
            "BT-720-Tender-Currency",
            "deadline-receipt-tender-date-lot",
            "contract-duration-period-lot",
            "duration-period-value-lot",
            "duration-period-unit-lot",
            "quantity-lot",
            "quantity-unit-lot",
            "main-classification-proc",
            "main-classification-lot",
        ],
        "page": page,
        "limit": limit,
        "scope": "ALL",
        "onlyLatestVersions": True,
    }
    response = requests.post(TED_SEARCH_URL, json=body, timeout=60)
    if response.status_code >= 400:
        raise RuntimeError(f"TED search failed: {response.status_code} {response.text}")
    response.raise_for_status()
    payload = response.json()
    return payload.get("notices") or []


def _download_xml(publication_number: str) -> ET.Element:
    url = f"https://ted.europa.eu/en/notice/{publication_number}/xml"
    for attempt in range(1, 5):
        response = requests.get(url, timeout=60)
        if response.status_code != 429:
            response.raise_for_status()
            return ET.fromstring(response.content)
        retry_after = response.headers.get("Retry-After")
        try:
            wait_seconds = int(retry_after) if retry_after else attempt * 5
        except ValueError:
            wait_seconds = attempt * 5
        time.sleep(wait_seconds)
    response.raise_for_status()
    return ET.fromstring(response.content)


def _organization_names(root: ET.Element) -> dict[str, str]:
    names: dict[str, str] = {}
    for org in root.findall(".//efac:Organizations/efac:Organization", NS):
        org_id = _first_text(org, ".//cac:PartyIdentification/cbc:ID")
        org_name = _first_text(org, ".//cac:PartyName/cbc:Name")
        if org_id and org_name:
            names[org_id] = org_name
    return names


def _tendering_party_to_org(root: ET.Element) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for party in root.findall(".//efac:NoticeResult/efac:TenderingParty", NS):
        party_id = _first_text(party, "cbc:ID")
        org_id = _first_text(party, ".//efac:Tenderer/cbc:ID")
        if party_id and org_id:
            mapping[party_id] = org_id
    return mapping


def _lot_metadata(root: ET.Element) -> dict[str, dict[str, str]]:
    lots: dict[str, dict[str, str]] = {}
    for lot in root.findall(".//cac:ProcurementProjectLot", NS):
        lot_id = _first_text(lot, "cbc:ID")
        project = lot.find("cac:ProcurementProject", NS)
        if not lot_id or project is None:
            continue
        duration = ""
        duration_node = project.find(".//cac:PlannedPeriod/cbc:DurationMeasure", NS)
        if duration_node is not None and _text(duration_node.text):
            unit = _text(duration_node.attrib.get("unitCode"))
            duration = " ".join(part for part in [_text(duration_node.text), unit] if part)
        lots[lot_id] = {
            "title": _first_text(project, "cbc:Name"),
            "description": _first_text(project, "cbc:Description"),
            "classification": _first_text(project, ".//cac:MainCommodityClassification/cbc:ItemClassificationCode"),
            "contract_period": duration,
        }
    return lots


def _tender_metadata(root: ET.Element) -> dict[str, dict[str, str]]:
    party_to_org = _tendering_party_to_org(root)
    org_names = _organization_names(root)
    tenders: dict[str, dict[str, str]] = {}
    for tender in root.findall(".//efac:NoticeResult/efac:LotTender", NS):
        tender_id = _first_text(tender, "cbc:ID")
        lot_id = _first_text(tender, "efac:TenderLot/cbc:ID")
        party_id = _first_text(tender, "efac:TenderingParty/cbc:ID")
        amount_node = tender.find(".//cac:LegalMonetaryTotal/cbc:PayableAmount", NS)
        value = _text(amount_node.text if amount_node is not None else "")
        currency = _text(amount_node.attrib.get("currencyID") if amount_node is not None else "")
        if tender_id:
            tenders[tender_id] = {
                "lot_id": lot_id,
                "supplier": org_names.get(party_to_org.get(party_id, ""), ""),
                "value": value,
                "currency": currency,
            }
    return tenders


def _contract_dates(root: ET.Element) -> dict[str, str]:
    dates: dict[str, str] = {}
    for contract in root.findall(".//efac:NoticeResult/efac:SettledContract", NS):
        contract_id = _first_text(contract, "cbc:ID")
        tender_id = _first_text(contract, "efac:LotTender/cbc:ID")
        issue_date = _parse_date(_first_text(contract, "cbc:IssueDate"))
        if tender_id:
            dates[tender_id] = issue_date or contract_id
    return dates


def _extract_quantity_and_uom(text: str) -> tuple[str, str]:
    cleaned = _text(text)
    match = re.search(r"\b(\d+(?:[.,]\d+)?)\s*(buc\.?|db|darab|unit[aă]ți|unitati|seturi|kituri|flacoane?)\b", cleaned, re.I)
    if match:
        return _text(match.group(1)), _text(match.group(2)).rstrip(".")
    return "", ""


def _unit_price(value: str, quantity: str) -> str:
    try:
        value_num = Decimal(_text(value).replace(",", ""))
        quantity_num = Decimal(_text(quantity).replace(",", "."))
    except InvalidOperation:
        return ""
    if not quantity_num:
        return ""
    result = value_num / quantity_num
    return f"{result:.2f}".rstrip("0").rstrip(".")


def _rows_from_xml(
    *,
    notice: dict[str, Any],
    root: ET.Element,
    country_name: str,
    country_cc: str,
    query_text: str,
) -> list[dict[str, str]]:
    publication_number = _text(notice.get("publication-number"))
    publication_date = _parse_date(_text(notice.get("publication-date")))
    title = _preferred_i18n(notice.get("title-proc"))
    buyer = _preferred_i18n(notice.get("buyer-name"))
    proc_description = _preferred_i18n(notice.get("description-proc"))
    lots = _lot_metadata(root)
    tenders = _tender_metadata(root)
    contract_dates = _contract_dates(root)

    rows: list[dict[str, str]] = []
    for result in root.findall(".//efac:NoticeResult/efac:LotResult", NS):
        result_code = _first_text(result, "cbc:TenderResultCode")
        if result_code and result_code != "selec-w":
            continue
        lot_id = _first_text(result, "efac:TenderLot/cbc:ID")
        tender_id = _first_text(result, "efac:LotTender/cbc:ID")
        tender = tenders.get(tender_id, {})
        lot = lots.get(lot_id, {})
        item_desc = lot.get("title") or title
        description = lot.get("description") or proc_description or title
        item_quantity, item_uom = _extract_quantity_and_uom(f"{item_desc} {description}")
        currency = tender.get("currency")
        awarded_value = tender.get("value")
        if not awarded_value:
            lower = result.find("cbc:LowerTenderAmount", NS)
            awarded_value = _text(lower.text if lower is not None else "")
            currency = currency or _text(lower.attrib.get("currencyID") if lower is not None else "")
        item_unit_price = _unit_price(awarded_value, item_quantity) if awarded_value and item_quantity else ""
        row = OutputRow(
            source="ted.europa.eu",
            country=country_name,
            country_cc=country_cc,
            publication_date=publication_date,
            closing_date="",
            title=title,
            description=description,
            buyer=buyer,
            classification=lot.get("classification") or ",".join(_list_i18n(notice.get("main-classification-proc"))),
            status="Awarded",
            currency=currency,
            amount=awarded_value,
            awarding_supplier_name=tender.get("supplier") or _preferred_i18n(notice.get("winner-name")),
            awarded_currency=currency,
            awarded_value=awarded_value,
            contract_period=lot.get("contract_period") or contract_dates.get(tender_id, ""),
            item_no=lot_id,
            item_desc=item_desc,
            item_uom=item_uom,
            item_quantity=item_quantity,
            item_unit_price=item_unit_price,
            item_award=awarded_value,
            notice_id=publication_number,
            notice_url=f"https://ted.europa.eu/en/notice/{publication_number}/html",
            query_text=query_text,
            scraped_at=utc_now_iso(),
            dedup_key=f"ted|{country_cc}|{publication_number}|{lot_id}",
        )
        rows.append(row.to_dict())
    return rows


def _rows_from_search_notice(
    *,
    notice: dict[str, Any],
    country_name: str,
    country_cc: str,
    query_text: str,
) -> list[dict[str, str]]:
    publication_number = _text(notice.get("publication-number"))
    publication_date = _parse_date(_text(notice.get("publication-date")))
    title = _preferred_i18n(notice.get("title-proc"))
    lot_titles = _dedupe_preserve(_list_i18n(notice.get("title-lot")))
    classifications = _dedupe_preserve(_list_i18n(notice.get("main-classification-lot"))) or _dedupe_preserve(_list_i18n(
        notice.get("main-classification-proc")
    ))
    winners = _dedupe_preserve(_list_i18n(notice.get("winner-name")))
    values = _dedupe_preserve(
        _list_i18n(notice.get("BT-660-LotResult"))
        or _list_i18n(notice.get("BT-711-LotResult"))
        or _list_i18n(notice.get("BT-720-Tender"))
        or _list_i18n(notice.get("tender-value"))
        or _list_i18n(notice.get("total-value"))
    )
    currencies = _dedupe_preserve(
        _list_i18n(notice.get("BT-660-LotResult-Currency"))
        or _list_i18n(notice.get("BT-711-LotResult-Currency"))
        or _list_i18n(notice.get("BT-720-Tender-Currency"))
        or _list_i18n(notice.get("tender-value-cur"))
    )
    buyer = _preferred_i18n(notice.get("buyer-name"))
    description = _preferred_i18n(notice.get("description-proc")) or title
    closing_dates = _dedupe_preserve(_list_i18n(notice.get("deadline-receipt-tender-date-lot")))
    contract_periods = _dedupe_preserve(
        _list_i18n(notice.get("contract-duration-period-lot"))
        or [
            " ".join(part for part in pair if part)
            for pair in zip(
                _list_i18n(notice.get("duration-period-value-lot")),
                _list_i18n(notice.get("duration-period-unit-lot")),
            )
        ]
    )
    quantities = _dedupe_preserve(_list_i18n(notice.get("quantity-lot")))
    quantity_units = _dedupe_preserve(_list_i18n(notice.get("quantity-unit-lot")))

    # Value arrays can include every received tender, not just awarded lots. Do not let them create rows.
    row_count = max(len(lot_titles), len(classifications), len(winners), 1)
    rows: list[dict[str, str]] = []
    for index in range(row_count):
        lot_title = lot_titles[index] if index < len(lot_titles) else title
        classification = classifications[index] if index < len(classifications) else ",".join(classifications)
        supplier = winners[index] if index < len(winners) else _preferred_i18n(notice.get("winner-name"))
        value = values[index] if index < len(values) else _preferred_i18n(notice.get("total-value"))
        currency = currencies[index] if index < len(currencies) else _preferred_i18n(notice.get("tender-value-cur"))
        closing_date = closing_dates[index] if index < len(closing_dates) else _preferred_i18n(notice.get("deadline-receipt-tender-date-lot"))
        contract_period = contract_periods[index] if index < len(contract_periods) else _preferred_i18n(notice.get("contract-duration-period-lot"))
        quantity = quantities[index] if index < len(quantities) else ""
        quantity_unit = quantity_units[index] if index < len(quantity_units) else ""
        item_unit_price = _unit_price(value, quantity) if value and quantity else ""
        item_no = f"SEARCH-LOT-{index + 1:04d}" if row_count > 1 else "SEARCH-LOT-0001"
        row = OutputRow(
            source="ted.europa.eu",
            country=country_name,
            country_cc=country_cc,
            publication_date=publication_date,
            closing_date=_parse_date(closing_date),
            title=title,
            description=description,
            buyer=buyer,
            classification=classification,
            status="Awarded",
            currency=currency,
            amount=value,
            awarding_supplier_name=supplier,
            awarded_currency=currency,
            awarded_value=value,
            contract_period=contract_period,
            item_no=item_no,
            item_desc=lot_title,
            item_uom=quantity_unit,
            item_quantity=quantity,
            item_unit_price=item_unit_price,
            item_award=value,
            notice_id=publication_number,
            notice_url=f"https://ted.europa.eu/en/notice/{publication_number}/html",
            query_text=f"{query_text}:search-fallback",
            scraped_at=utc_now_iso(),
            dedup_key=f"ted|{country_cc}|{publication_number}|{item_no}",
        )
        rows.append(row.to_dict())
    return rows


def _dedup_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    deduped: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        key = row.get("dedup_key") or row.get("notice_id") or str(row)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def collect_rows(
    country_code: str,
    date_from: str,
    date_to: str,
    *,
    limit: int,
    pages: int,
    cpvs: list[str],
    prefer_xml: bool = True,
) -> list[dict[str, str]]:
    country_names = {"HUN": ("Hungary", "HU"), "ROU": ("Romania", "RO")}
    country_name, country_cc = country_names[country_code]
    rows: list[dict[str, str]] = []
    seen_publications: set[str] = set()
    for cpv in cpvs:
        for page in range(1, pages + 1):
            query_text = f"ted-medical-awards:{country_code}:{date_from}..{date_to}:cpv={cpv}:page={page}"
            notices = _search_notices(country_code, date_from, date_to, cpv=cpv, page=page, limit=limit)
            if not notices:
                break
            for notice in notices:
                publication_number = _text(notice.get("publication-number"))
                if (
                    not publication_number
                    or publication_number in seen_publications
                    or not _preferred_i18n(notice.get("winner-name"))
                ):
                    continue
                seen_publications.add(publication_number)
                if not prefer_xml:
                    rows.extend(
                        _rows_from_search_notice(
                            notice=notice,
                            country_name=country_name,
                            country_cc=country_cc,
                            query_text=query_text,
                        )
                    )
                    continue
                try:
                    root = _download_xml(publication_number)
                except requests.HTTPError as exc:
                    if exc.response is not None and exc.response.status_code == 429:
                        time.sleep(10)
                    rows.extend(
                        _rows_from_search_notice(
                            notice=notice,
                            country_name=country_name,
                            country_cc=country_cc,
                            query_text=query_text,
                        )
                    )
                    continue
                rows.extend(
                    _rows_from_xml(
                        notice=notice,
                        root=root,
                        country_name=country_name,
                        country_cc=country_cc,
                        query_text=query_text,
                    )
                )
                time.sleep(0.5)

    rows = _dedup_rows(rows)
    return rows


def export(
    country_code: str,
    date_from: str,
    date_to: str,
    output_path: Path,
    *,
    limit: int,
    pages: int,
    cpvs: list[str],
    prefer_xml: bool = True,
) -> None:
    rows = collect_rows(
        country_code,
        date_from,
        date_to,
        limit=limit,
        pages=pages,
        cpvs=cpvs,
        prefer_xml=prefer_xml,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(output_path.resolve())
    print(f"rows={len(rows)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe TED awarded medical/healthcare notices into ACEE schema.")
    parser.add_argument("--country-code", choices=["HUN", "ROU"], required=True)
    parser.add_argument("--date-from", default="2024-01-01")
    parser.add_argument("--date-to", default=date.today().isoformat())
    parser.add_argument("--output", required=True)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--pages", type=int, default=1)
    parser.add_argument(
        "--search-only",
        action="store_true",
        help="Use TED search-result fields only. This avoids XML rate limits but cannot recover XML-only fields.",
    )
    parser.add_argument(
        "--cpv",
        action="append",
        dest="cpvs",
        help="Exact main CPV to query. Repeat for multiple CPVs. Defaults to a curated medical CPV list.",
    )
    args = parser.parse_args()
    export(
        args.country_code,
        args.date_from,
        args.date_to,
        Path(args.output),
        limit=args.limit,
        pages=args.pages,
        cpvs=args.cpvs or list(DEFAULT_MEDICAL_CPVS),
        prefer_xml=not args.search_only,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
