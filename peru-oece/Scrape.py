import argparse
import asyncio
import csv
import logging
from dataclasses import dataclass, asdict
from typing import Dict, Iterable, List, Optional
from urllib.parse import parse_qs, urlparse, urlunparse

from playwright.async_api import APIResponse, async_playwright


API_ENDPOINT = "https://contratacionesabiertas.oece.gob.pe/api/v1/buyerContracts"
DEFAULT_FIELDS = [
    "contract_id",
    "supplier",
    "signed_date",
    "amount",
    "currency",
    "procurement_method",
    "object",
    "status",
    "detail_url",
    "tender_id",
    "winner_local",
    "segment",
    "segment_name",
    "item_description_en",
    "quantity",
    "unit_price",
    "total_amount_original",
    "publication_date",
    "resolution_date",
]


@dataclass
class ContractRecord:
    contract_id: Optional[str] = None
    supplier: Optional[str] = None
    signed_date: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    procurement_method: Optional[str] = None
    object: Optional[str] = None
    status: Optional[str] = None
    detail_url: Optional[str] = None
    tender_id: Optional[str] = None
    winner_local: Optional[str] = None
    segment: Optional[str] = None
    segment_name: Optional[str] = None
    item_description_en: Optional[str] = None
    quantity: Optional[float] = None
    unit_price: Optional[float] = None
    total_amount_original: Optional[float] = None
    publication_date: Optional[str] = None
    resolution_date: Optional[str] = None


def parse_entity_url(entity_url: str) -> Dict[str, str]:
    parsed = urlparse(entity_url)
    entity_id = parsed.path.rstrip("/").split("/")[-1]
    params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
    params.setdefault("contractsPage", "1")
    params.setdefault("contractsPaginateBy", "10")
    params.setdefault("typeContractDateSigned", "between")
    params.setdefault("orderContractDateSigned", "asc")
    params.setdefault("orderContractSupplier", "asc")
    params["buyerID"] = entity_id
    params["format"] = "json"
    return params


async def fetch_page(
    request_context,
    params: Dict[str, str],
) -> Dict:
    response: APIResponse = await request_context.get(API_ENDPOINT, params=params, timeout=120000)
    if not response.ok:
        raise RuntimeError(f"API error {response.status}: {await response.text()}")
    return await response.json()


def build_detail_url(ocid: str, contract_id: str) -> str:
    parsed = urlparse(f"https://contratacionesabiertas.oece.gob.pe/proceso/{ocid}?contract={contract_id}")
    return urlunparse(parsed)


def iter_items(contract: Dict) -> Iterable[Dict]:
    compiled = contract.get("compiledRelease", {}) or {}
    contract_block = compiled.get("contract") or {}
    items = contract_block.get("items") or contract.get("items") or []
    if not items:
        yield {}
    else:
        for item in items:
            yield item or {}


def map_suppliers(contract: Dict) -> str:
    suppliers = contract.get("suppliers") or contract.get("award", {}).get("suppliers") or []
    return "; ".join(sorted({s.get("name") for s in suppliers if s.get("name")})) or ""


def map_winners(contract: Dict) -> str:
    winners = contract.get("award", {}).get("suppliers") or []
    return "; ".join(sorted({s.get("name") for s in winners if s.get("name")})) or ""


def record_from_contract(contract: Dict, item: Dict) -> ContractRecord:
    compiled = contract.get("compiledRelease", {}) or {}
    tender = compiled.get("tender") or {}
    publication_date = tender.get("datePublished")
    procurement_method = tender.get("procurementMethodDetails") or tender.get("procurementMethod")
    award = contract.get("award") or {}
    detail_url = build_detail_url(contract.get("ocid", ""), contract.get("id", ""))
    supplier_names = map_suppliers(contract)
    winner_names = map_winners(contract)
    total_value = (item or {}).get("totalValue") or {}
    quantity = item.get("quantity") if item else None
    total_amount = total_value.get("amount")
    unit_price = None
    if total_amount is not None and quantity not in (None, 0):
        unit_price = total_amount / quantity
    return ContractRecord(
        contract_id=contract.get("id"),
        supplier=supplier_names,
        signed_date=contract.get("dateSigned"),
        amount=(contract.get("value") or {}).get("amount"),
        currency=(contract.get("value") or {}).get("currency"),
        procurement_method=procurement_method,
        object=contract.get("description"),
        status=(item or {}).get("statusDetails") or (item or {}).get("status"),
        detail_url=detail_url,
        tender_id=contract.get("tenderId") or tender.get("id"),
        winner_local=winner_names or supplier_names,
        segment=(item.get("classification") or {}).get("id") if item else None,
        segment_name=(item.get("classification") or {}).get("description") if item else None,
        item_description_en=item.get("description") if item else None,
        quantity=quantity,
        unit_price=unit_price,
        total_amount_original=total_amount,
        publication_date=publication_date,
        resolution_date=award.get("date"),
    )


async def scrape_contracts(entity_url: str, output: str, max_pages: Optional[int] = None) -> None:
    base_params = parse_entity_url(entity_url)
    page_size = int(base_params.get("contractsPaginateBy", "10"))
    results: List[ContractRecord] = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(locale="es-PE")
        page = await context.new_page()
        await page.goto(entity_url, wait_until="domcontentloaded")

        current_page = 1
        total_pages = None
        while True:
            if max_pages and current_page > max_pages:
                break
            params = dict(base_params)
            params["contractsPage"] = str(current_page)
            logging.info("Fetching contracts page %s", current_page)
            data = await fetch_page(context.request, params)
            page_results = data.get("results") or []
            for contract in page_results:
                for item in iter_items(contract):
                    results.append(record_from_contract(contract, item))

            pagination = data.get("pagination") or {}
            total_pages = pagination.get("num_pages") or total_pages
            has_next = pagination.get("has_next")
            if not has_next or (total_pages and current_page >= total_pages):
                break
            current_page += 1

        await browser.close()

    if not results:
        raise RuntimeError("No contract data was collected.")

    with open(output, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=DEFAULT_FIELDS)
        writer.writeheader()
        for record in results:
            writer.writerow(asdict(record))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape contract and award details for a buyer entity.")
    parser.add_argument(
        "--entity-url",
        required=True,
        help="Entity page URL with desired query parameters, e.g. "
        "https://contratacionesabiertas.oece.gob.pe/entidad/<PE-ID>?contractsPage=1&contractsPaginateBy=10&…",
    )
    parser.add_argument("--output", default="contracts_with_awards(test).csv", help="Path to the CSV output file")
    parser.add_argument("--max-pages", type=int, default=None, help="Limit pagination for debugging/testing.")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    asyncio.run(scrape_contracts(args.entity_url, args.output, args.max_pages))


if __name__ == "__main__":
    main()
