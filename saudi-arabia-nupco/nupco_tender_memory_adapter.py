from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit
from urllib.request import Request, build_opener

import pdfplumber
from lxml import html as lxml_html


ROOT = Path(__file__).resolve().parent
EVIDENCE_ROOT = ROOT / "tender_memory_output" / "adapter_evidence"
REQUEST_TIMEOUT = (20, 180)


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _slug(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_")
    return value or "notice"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _iso_date(value: str) -> str:
    text = _clean(value)
    text = re.sub(r"^[A-Za-z]{3,9},\s*", "", text)
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return ""


def _session() -> Any:
    return build_opener()


@dataclass
class Fetched:
    url: str
    content: bytes
    content_type: str

    @property
    def text(self) -> str:
        charset_match = re.search(r"charset=([^;\s]+)", self.content_type, re.I)
        charset = charset_match.group(1).strip('"\'') if charset_match else "utf-8"
        try:
            return self.content.decode(charset, errors="replace")
        except LookupError:
            return self.content.decode("utf-8", errors="replace")


def _fetch(session: Any, url: str) -> Fetched:
    last_error: Exception | None = None
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/138 Safari/537.36"
        )
    }
    parts = urlsplit(url)
    url = urlunsplit(
        (
            parts.scheme,
            parts.netloc.encode("idna").decode("ascii"),
            quote(unquote(parts.path), safe="/%:@-._~!$&'()*+,;="),
            quote(unquote(parts.query), safe="=&?/%:@-._~!$'()*+,;"),
            "",
        )
    )
    for attempt in range(4):
        try:
            request = Request(url, headers=headers, method="GET")
            with session.open(request, timeout=max(REQUEST_TIMEOUT)) as response:
                return Fetched(
                    url=response.geturl(),
                    content=response.read(),
                    content_type=response.headers.get("Content-Type", ""),
                )
        except Exception as exc:
            last_error = exc
            if attempt < 3:
                time.sleep(1.0 * (2**attempt))
    assert last_error is not None
    raise last_error


def _label_value(strings: list[str], labels: tuple[str, ...]) -> str:
    wanted = {label.casefold().rstrip(":") for label in labels}
    for index, value in enumerate(strings):
        if value.casefold().rstrip(":") not in wanted:
            continue
        for candidate in strings[index + 1 : index + 5]:
            if candidate.casefold().rstrip(":") not in wanted:
                return candidate
    return ""


def _parse_detail(html: str, final_url: str, fallback_notice_id: str) -> dict[str, Any]:
    document = lxml_html.fromstring(html)
    strings = [_clean(item) for item in document.xpath("//text()[normalize-space()]")]
    strings = [item for item in strings if item]
    heading_texts = [
        _clean(" ".join(node.itertext()))
        for node in document.xpath("//h1|//h2|//h3|//h4")
    ]
    heading_texts = [
        item
        for item in heading_texts
        if item and item.casefold() not in {"tender id", "tender booklet price"}
    ]
    title = max(heading_texts, key=len, default="")

    notice_id = _label_value(strings, ("Tender ID", "Tender Id", "Tendr Id")) or fallback_notice_id
    opening_date = _iso_date(_label_value(strings, ("Opening Date",)))
    closing_date = _iso_date(_label_value(strings, ("Submission Deadline",)))
    bid_opening_date = _iso_date(_label_value(strings, ("Bid Opening", "Bid Opening Date")))
    status = next((item for item in strings if item.casefold() in {"final result", "final results"}), "")

    attachments: list[dict[str, str]] = []
    for anchor in document.xpath("//a[@href]"):
        href = _clean(anchor.get("href"))
        if not href or ".pdf" not in href.casefold():
            continue
        attachments.append(
            {
                "label": _clean(" ".join(anchor.itertext())) or unquote(href.rsplit("/", 1)[-1]),
                "url": urljoin(final_url, href),
            }
        )

    final_attachments = []
    for item in attachments:
        signal = f"{item['label']} {unquote(item['url'])}".casefold()
        if ("final" in signal and ("result" in signal or "award" in signal)) or "final-award" in signal:
            final_attachments.append(item)

    return {
        "notice_id": notice_id,
        "notice_url": final_url,
        "title": title,
        "publication_date": opening_date,
        "closing_date": closing_date,
        "bid_opening_date": bid_opening_date,
        "status": "Final Result" if status or final_attachments else "",
        "attachments": attachments,
        "final_attachments": final_attachments,
    }


def _header_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _clean(value).casefold()).strip()


def _find_column(headers: list[str], predicates: tuple[tuple[str, ...], ...]) -> int | None:
    for required in predicates:
        for index, header in enumerate(headers):
            if all(token in header for token in required):
                return index
    return None


def _table_columns(raw_headers: list[Any]) -> dict[str, int]:
    headers = [_header_key(item) for item in raw_headers]
    columns: dict[str, int] = {}
    specs = {
        "item_no": (("sn",), ("s n",), ("item", "no"), ("serial", "no")),
        "item_code": (("nupco", "code"), ("srm", "code"), ("item", "code")),
        "item_description": (
            ("item", "description"),
            ("item", "name"),
            ("item", "specification"),
            ("description",),
        ),
        "correct_uom": (("correct", "uom"),),
        "item_uom": (("uom",), ("unit", "measure")),
        "group": (("group",),),
        "vendor_no": (("vendor", "no"), ("supplier", "code"), ("vendor", "code")),
        "supplier_name": (("vendor", "name"), ("supplier", "name")),
        "manufacturer": (("manufacturer",),),
        "country_of_origin": (("country",),),
        "catalog_no": (("catalog", "no"), ("model",)),
        "sector_name": (("sector", "name"), ("sector",)),
        "item_quantity": (("quantity",), ("qty",)),
        "awarded_date": (("award", "date"), ("awarded", "date")),
        "contract_period": (("contract", "period"), ("contract", "duration"), ("duration",)),
        "item_unit_price": (("unit", "price"), ("unit", "rate"), ("awarded", "unit", "price")),
        "item_awarded_value": (
            ("total", "value"),
            ("awarded", "value"),
            ("total", "price"),
            ("line", "amount"),
        ),
    }
    for field, predicates in specs.items():
        index = _find_column(headers, predicates)
        if index is not None:
            columns[field] = index
    # Some official result tables label the vendor column simply "SUPPLIER".
    # Prefer that exact header over the adjacent "SUPPLIER CODE" field.
    exact_supplier = next(
        (index for index, header in enumerate(headers) if header in {"supplier", "vendor"}),
        None,
    )
    if exact_supplier is not None:
        columns["supplier_name"] = exact_supplier
    # Prefer the explicit corrected unit over the raw source unit.
    if "correct_uom" in columns:
        columns["item_uom"] = columns["correct_uom"]
    return columns


def _cell(row: list[Any], index: int | None) -> str:
    if index is None or index >= len(row):
        return ""
    return _clean(row[index])


def _parse_pdf_tables(data: bytes, evidence_url: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    page_count = 0
    table_count = 0
    with pdfplumber.open(BytesIO(data)) as pdf:
        page_count = len(pdf.pages)
        for page_number, page in enumerate(pdf.pages, start=1):
            tables = page.extract_tables() or []
            table_count += len(tables)
            for table in tables:
                if not table:
                    continue
                # Some one-page PDFs encode each visual column as several sparse
                # PDF cells. Collapse those spacer cells before header matching so
                # values align with their logical columns.
                working_table = table
                for candidate in table[:6]:
                    candidate = candidate or []
                    populated = sum(bool(_clean(cell)) for cell in candidate)
                    if len(candidate) >= 8 and populated and populated <= len(candidate) * 0.6:
                        working_table = [
                            [cell for cell in (row or []) if _clean(cell)]
                            for row in table
                        ]
                        break
                header_index = None
                columns: dict[str, int] = {}
                for candidate_index, candidate in enumerate(working_table[:6]):
                    candidate_columns = _table_columns(candidate or [])
                    if "item_description" in candidate_columns and (
                        "supplier_name" in candidate_columns or "item_quantity" in candidate_columns
                    ):
                        header_index = candidate_index
                        columns = candidate_columns
                        break
                if header_index is None:
                    continue

                for raw_row in working_table[header_index + 1 :]:
                    if not raw_row:
                        continue
                    description = _cell(raw_row, columns.get("item_description"))
                    supplier = _cell(raw_row, columns.get("supplier_name"))
                    item_no = _cell(raw_row, columns.get("item_no"))
                    item_code = _cell(raw_row, columns.get("item_code"))
                    quantity = _cell(raw_row, columns.get("item_quantity")).replace(",", "")
                    # An awarded row must identify both the awarded item and final vendor.
                    # Rows without either field are usually continued headers, blank cells,
                    # or unawarded lines in a mixed result workbook.
                    if not description or not supplier:
                        continue
                    if _header_key(description) in {"item description", "item name"}:
                        continue

                    awarded_date = _iso_date(_cell(raw_row, columns.get("awarded_date")))
                    contract_period = _clean(_cell(raw_row, columns.get("contract_period")))
                    contract_period = re.sub(r"\b(years?)\b", "Years", contract_period, flags=re.I)
                    contract_period = re.sub(r"\b(months?)\b", "Months", contract_period, flags=re.I)
                    contract_period = re.sub(r"\b(days?)\b", "Days", contract_period, flags=re.I)
                    row = {
                        "item_no": item_no,
                        "item_code": item_code,
                        "item_description": description,
                        "item_uom": _cell(raw_row, columns.get("item_uom")).upper(),
                        "item_quantity": quantity,
                        "supplier_name": supplier,
                        "vendor_no": _cell(raw_row, columns.get("vendor_no")),
                        "manufacturer": _cell(raw_row, columns.get("manufacturer")),
                        "country_of_origin": _cell(raw_row, columns.get("country_of_origin")),
                        "catalog_no": _cell(raw_row, columns.get("catalog_no")),
                        "sector_name": _cell(raw_row, columns.get("sector_name")),
                        "group": _cell(raw_row, columns.get("group")),
                        "awarded_date": awarded_date,
                        "contract_period": contract_period,
                        "item_unit_price": _cell(raw_row, columns.get("item_unit_price")).replace(",", ""),
                        "item_awarded_value": _cell(raw_row, columns.get("item_awarded_value")).replace(",", ""),
                        "evidence_url": evidence_url,
                        "evidence_page": page_number,
                    }
                    rows.append(row)
    return rows, {"page_count": page_count, "table_count": table_count}


def _deduplicate(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        identity = "|".join(
            _clean(row.get(key)).casefold()
            for key in (
                "item_no",
                "item_code",
                "supplier_name",
                "sector_name",
                "item_description",
                "item_quantity",
            )
        )
        if identity in seen:
            continue
        seen.add(identity)
        output.append(row)
    return output


def _fallback_rows(target: dict[str, Any], metadata: dict[str, Any]) -> list[dict[str, Any]]:
    """Evidence-conservative fallback when a final PDF is not table-readable."""
    rows = []
    for source_row in target.get("source_rows", []):
        row = dict(source_row)
        row.update(
            {
                "publication_date": metadata.get("publication_date", ""),
                "closing_date": metadata.get("closing_date", ""),
                "status": "Final Result",
                "status_en": "Final Result",
                "notice_url": metadata.get("notice_url", ""),
                "amount": "",
                "currency": "",
                "awarded_value_detail": "",
                "contract_period": "",
                "item_unit_price": "",
                "item_awarded_value": "",
                "correction_note": (
                    "Notice metadata corrected from the official NUPCO page; item-level fields retained "
                    "because the final-award attachment was not table-readable."
                ),
            }
        )
        rows.append(row)
    return rows


class Adapter:
    def __init__(self, url: str):
        self.url = url
        self.session = _session()
        EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)

    def extract(self, source: Any) -> list[dict[str, Any]]:
        raise NotImplementedError("This adapter is intended for targeted repair via extract_targets")

    def extract_targets(self, source: Any, targets: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        replacements: dict[str, list[dict[str, Any]]] = {}
        audit: dict[str, Any] = {
            "adapter": str(Path(__file__).resolve()),
            "started_at_utc": datetime.now(timezone.utc).isoformat(),
            "target_count": len(targets),
            "targets": [],
        }

        for index, target in enumerate(targets, start=1):
            target_key = target["target_key"]
            notice_id = _clean(target.get("notice_id"))
            source_rows = target.get("source_rows") or []
            requested_url = _clean(target.get("notice_url"))
            if not requested_url:
                requested_url = next(
                    (
                        _clean(row.get("original_notice_url") or row.get("notice_url"))
                        for row in source_rows
                        if _clean(row.get("original_notice_url") or row.get("notice_url"))
                    ),
                    "",
                )
            target_log: dict[str, Any] = {
                "target_key": target_key,
                "notice_id": notice_id,
                "requested_url": requested_url,
                "status": "started",
            }
            print(f"[{index}/{len(targets)}] Re-extracting {notice_id or target_key}", flush=True)
            try:
                notice_dir = EVIDENCE_ROOT / _slug(notice_id)
                cache_path = notice_dir / "replacement_cache.json"
                if cache_path.is_file():
                    output_rows = json.loads(cache_path.read_text(encoding="utf-8"))
                    if not isinstance(output_rows, list) or not output_rows:
                        raise RuntimeError(f"Invalid or empty replacement cache: {cache_path}")
                    replacements[target_key] = output_rows
                    target_log.update(
                        {
                            "status": "resolved",
                            "replacement_row_count": len(output_rows),
                            "replacement_cache": str(cache_path.resolve()),
                        }
                    )
                    audit["targets"].append(target_log)
                    continue

                response = _fetch(self.session, requested_url)
                metadata = _parse_detail(response.text, response.url, notice_id)
                final_attachments = metadata["final_attachments"]
                target_log.update(
                    {
                        "resolved_notice_url": response.url,
                        "publication_date": metadata.get("publication_date"),
                        "closing_date": metadata.get("closing_date"),
                        "bid_opening_date": metadata.get("bid_opening_date"),
                        "final_attachment_count": len(final_attachments),
                    }
                )
                if not final_attachments:
                    raise RuntimeError("Official detail page does not expose a final-result attachment")

                notice_dir = EVIDENCE_ROOT / _slug(metadata.get("notice_id") or notice_id)
                notice_dir.mkdir(parents=True, exist_ok=True)
                parsed_rows: list[dict[str, Any]] = []
                attachment_logs = []
                for attachment_index, attachment in enumerate(final_attachments, start=1):
                    pdf_response = _fetch(self.session, attachment["url"])
                    data = pdf_response.content
                    filename = _slug(unquote(attachment["url"].rsplit("/", 1)[-1]))
                    if not filename.casefold().endswith(".pdf"):
                        filename += ".pdf"
                    path = notice_dir / f"{attachment_index:02d}_{filename}"
                    path.write_bytes(data)
                    extracted, metrics = _parse_pdf_tables(data, attachment["url"])
                    parsed_rows.extend(extracted)
                    attachment_logs.append(
                        {
                            "label": attachment["label"],
                            "url": attachment["url"],
                            "path": str(path.resolve()),
                            "sha256": _sha256(data),
                            "bytes": len(data),
                            "extracted_rows": len(extracted),
                            **metrics,
                        }
                    )

                parsed_rows = _deduplicate(parsed_rows)
                first_source = (target.get("source_rows") or [{}])[0]
                scraped_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
                if parsed_rows:
                    output_rows = []
                    for item in parsed_rows:
                        output_rows.append(
                            {
                                "source": "NUPCO Tenders and Awards",
                                "country": "Saudi Arabia",
                                "country_code": "SA",
                                "publication_date": metadata.get("publication_date", ""),
                                "closing_date": metadata.get("closing_date", ""),
                                "title": metadata.get("title", ""),
                                "title_en": first_source.get("title_en", ""),
                                "description": item.get("item_description", ""),
                                "description_en": item.get("item_description", ""),
                                "buyer": "NUPCO",
                                "buyer_en": "NUPCO",
                                "classification": "Medical supplies / equipment",
                                "classification_en": "Medical supplies / equipment",
                                "status": "Final Result",
                                "status_en": "Final Result",
                                "currency": "",
                                "amount": "",
                                "awarding_agency_name": "NUPCO",
                                "awarding_agency_name_en": "NUPCO",
                                "supplier_name": item.get("supplier_name", ""),
                                "supplier_name_en": item.get("supplier_name", ""),
                                "awarded_date": item.get("awarded_date", ""),
                                "awarded_value_detail": "",
                                "contract_period": "",
                                "contract_period_en": "",
                                "item_no": item.get("item_no", ""),
                                "item_code": item.get("item_code", ""),
                                "item_description": item.get("item_description", ""),
                                "item_description_en": item.get("item_description", ""),
                                "item_uom": item.get("item_uom", ""),
                                "item_quantity": item.get("item_quantity", ""),
                                "item_unit_price": item.get("item_unit_price", ""),
                                "item_awarded_value": item.get("item_awarded_value", ""),
                                "vendor_no": item.get("vendor_no", ""),
                                "manufacturer": item.get("manufacturer", ""),
                                "country_of_origin": item.get("country_of_origin", ""),
                                "catalog_no": item.get("catalog_no", ""),
                                "sector_name": item.get("sector_name", ""),
                                "group": item.get("group", ""),
                                "notice_id": metadata.get("notice_id") or notice_id,
                                "notice_url": metadata.get("notice_url", ""),
                                "evidence_url": item.get("evidence_url", ""),
                                "evidence_page": item.get("evidence_page", ""),
                                "query_text": "NUPCO Final Results and final-award attachment",
                                "scraped_at_utc": scraped_at,
                                "correction_note": (
                                    "Re-extracted from the official final-award attachment. Tender booklet price was not "
                                    "treated as an awarded value; unavailable price and contract fields are blank."
                                ),
                            }
                        )
                else:
                    output_rows = _fallback_rows(target, metadata)
                    target_log["fallback_used"] = True

                replacements[target_key] = output_rows
                cache_path = notice_dir / "replacement_cache.json"
                cache_path.write_text(
                    json.dumps(output_rows, indent=2, ensure_ascii=False), encoding="utf-8"
                )
                target_log.update(
                    {
                        "status": "resolved",
                        "replacement_row_count": len(output_rows),
                        "attachment_evidence": attachment_logs,
                    }
                )
            except Exception as exc:
                target_log.update({"status": "unresolved", "error": f"{type(exc).__name__}: {exc}"})
            audit["targets"].append(target_log)
            time.sleep(0.15)

        audit["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        audit["resolved_count"] = sum(item["status"] == "resolved" for item in audit["targets"])
        audit["unresolved_count"] = sum(item["status"] != "resolved" for item in audit["targets"])
        (EVIDENCE_ROOT / "adapter_handoff.json").write_text(
            json.dumps(audit, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return replacements


def create_adapter(url: str) -> Adapter:
    return Adapter(url)
